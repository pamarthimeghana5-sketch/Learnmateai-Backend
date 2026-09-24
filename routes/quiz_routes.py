import json
import re
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from db import get_db_connection
from services.ai_service import get_ai_response

quiz_bp = Blueprint("quiz", __name__, url_prefix="/api/quizzes")


def _get_owned_quiz(cur, quiz_id, user_id):
    cur.execute("SELECT * FROM quizzes WHERE id = %s AND user_id = %s", (quiz_id, user_id))
    return cur.fetchone()


def _extract_json_array(text):
    match = re.search(r"\[.*\]", text, re.DOTALL)
    return match.group(0) if match else text


@quiz_bp.route("", methods=["POST"])
@jwt_required()
def create_quiz():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    description = data.get("description", "")
    questions = data.get("questions", [])

    if not title:
        return jsonify({"success": False, "message": "Quiz title is required"}), 400
    if not questions:
        return jsonify({"success": False, "message": "At least one question is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO quizzes (user_id, title, description, source_type) VALUES (%s, %s, %s, 'manual')",
                (user_id, title, description),
            )
            quiz_id = cur.lastrowid

            for q in questions:
                cur.execute(
                    """
                    INSERT INTO quiz_questions
                        (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        quiz_id, q.get("questionText", ""), q.get("optionA", ""),
                        q.get("optionB", ""), q.get("optionC", ""), q.get("optionD", ""),
                        q.get("correctOption", "A").upper(),
                    ),
                )
            conn.commit()
        return jsonify({"success": True, "quiz": {"id": quiz_id, "title": title, "questionCount": len(questions)}}), 201
    finally:
        conn.close()


@quiz_bp.route("/generate", methods=["POST"])
@jwt_required()
def generate_quiz():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    document_id = data.get("documentId")
    num_questions = min(int(data.get("numQuestions", 5)), 20)
    title = (data.get("title") or "AI Generated Quiz").strip()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            content = ""
            if document_id:
                cur.execute(
                    "SELECT extracted_text FROM documents WHERE id = %s AND user_id = %s",
                    (document_id, user_id),
                )
                doc = cur.fetchone()
                if not doc:
                    return jsonify({"success": False, "message": "Document not found"}), 404
                content = (doc["extracted_text"] or "")[:8000]

            if not content.strip():
                return jsonify({"success": False, "message": "No source text available to build a quiz from"}), 400

            prompt = (
                f"Create {num_questions} multiple-choice questions from the text below. "
                f"Respond with ONLY a JSON array, no extra words, in this exact format:\n"
                f'[{{"questionText": "...", "optionA": "...", "optionB": "...", '
                f'"optionC": "...", "optionD": "...", "correctOption": "A"}}]\n\n'
                f"Text:\n{content}"
            )
            ai_text = get_ai_response([{"role": "user", "content": prompt}])

            try:
                questions = json.loads(_extract_json_array(ai_text))
            except (json.JSONDecodeError, TypeError):
                return jsonify({
                    "success": False,
                    "message": "AI response could not be parsed into quiz questions. Try again."
                }), 502

            cur.execute(
                "INSERT INTO quizzes (user_id, title, source_type, document_id) VALUES (%s, %s, 'ai-generated', %s)",
                (user_id, title, document_id),
            )
            quiz_id = cur.lastrowid

            for q in questions:
                cur.execute(
                    """
                    INSERT INTO quiz_questions
                        (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        quiz_id, q.get("questionText", ""), q.get("optionA", ""),
                        q.get("optionB", ""), q.get("optionC", ""), q.get("optionD", ""),
                        (q.get("correctOption") or "A").upper(),
                    ),
                )
            conn.commit()

        return jsonify({"success": True, "quiz": {"id": quiz_id, "title": title, "questionCount": len(questions)}}), 201
    finally:
        conn.close()


@quiz_bp.route("", methods=["GET"])
@jwt_required()
def my_quizzes():
    user_id = get_jwt_identity()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT q.id, q.title, q.description, q.source_type, q.created_at,
                       (SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = q.id) AS question_count,
                       (SELECT COUNT(*) FROM quiz_attempts WHERE quiz_id = q.id AND user_id = %s) AS attempt_count
                FROM quizzes q
                WHERE q.user_id = %s
                ORDER BY q.created_at DESC
                """,
                (user_id, user_id),
            )
            quizzes = cur.fetchall()
        return jsonify({"success": True, "quizzes": quizzes}), 200
    finally:
        conn.close()


@quiz_bp.route("/<int:quiz_id>", methods=["GET"])
@jwt_required()
def get_quiz_for_taking(quiz_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, description FROM quizzes WHERE id = %s", (quiz_id,))
            quiz = cur.fetchone()
            if not quiz:
                return jsonify({"success": False, "message": "Quiz not found"}), 404

            cur.execute(
                "SELECT id, question_text, option_a, option_b, option_c, option_d "
                "FROM quiz_questions WHERE quiz_id = %s",
                (quiz_id,),
            )
            questions = cur.fetchall()
        return jsonify({"success": True, "quiz": quiz, "questions": questions}), 200
    finally:
        conn.close()


@quiz_bp.route("/<int:quiz_id>/attempt", methods=["POST"])
@jwt_required()
def submit_attempt(quiz_id):
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    answers = data.get("answers", [])

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM quizzes WHERE id = %s", (quiz_id,))
            if not cur.fetchone():
                return jsonify({"success": False, "message": "Quiz not found"}), 404

            cur.execute(
                "SELECT id, correct_option FROM quiz_questions WHERE quiz_id = %s",
                (quiz_id,),
            )
            correct_map = {q["id"]: q["correct_option"] for q in cur.fetchall()}

            score = 0
            graded = []
            for a in answers:
                qid = a.get("questionId")
                selected = (a.get("selectedOption") or "").upper() or None
                is_correct = selected is not None and correct_map.get(qid) == selected
                if is_correct:
                    score += 1
                graded.append((qid, selected, is_correct))

            cur.execute(
                "INSERT INTO quiz_attempts (quiz_id, user_id, score, total_questions) VALUES (%s, %s, %s, %s)",
                (quiz_id, user_id, score, len(correct_map)),
            )
            attempt_id = cur.lastrowid

            for qid, selected, is_correct in graded:
                cur.execute(
                    "INSERT INTO quiz_answers (attempt_id, question_id, selected_option, is_correct) "
                    "VALUES (%s, %s, %s, %s)",
                    (attempt_id, qid, selected, is_correct),
                )
            conn.commit()

        return jsonify({
            "success": True,
            "attemptId": attempt_id,
            "score": score,
            "totalQuestions": len(correct_map),
        }), 201
    finally:
        conn.close()


@quiz_bp.route("/<int:quiz_id>/results", methods=["GET"])
@jwt_required()
def quiz_results(quiz_id):
    user_id = get_jwt_identity()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, score, total_questions, attempted_at FROM quiz_attempts "
                "WHERE quiz_id = %s AND user_id = %s ORDER BY attempted_at DESC",
                (quiz_id, user_id),
            )
            attempts = cur.fetchall()

            cur.execute(
                """
                SELECT qq.id AS question_id, qq.question_text,
                       SUM(qa.is_correct) AS correct_count,
                       COUNT(qa.id) AS attempt_count
                FROM quiz_questions qq
                LEFT JOIN quiz_answers qa ON qa.question_id = qq.id
                LEFT JOIN quiz_attempts qat ON qat.id = qa.attempt_id AND qat.user_id = %s
                WHERE qq.quiz_id = %s
                GROUP BY qq.id, qq.question_text
                """,
                (user_id, quiz_id),
            )
            per_question = cur.fetchall()

        best_score = max((a["score"] for a in attempts), default=0)
        return jsonify({
            "success": True,
            "attempts": attempts,
            "bestScore": best_score,
            "perQuestionAnalysis": per_question,
        }), 200
    finally:
        conn.close()


@quiz_bp.route("/<int:quiz_id>", methods=["DELETE"])
@jwt_required()
def delete_quiz(quiz_id):
    user_id = get_jwt_identity()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            quiz = _get_owned_quiz(cur, quiz_id, user_id)
            if not quiz:
                return jsonify({"success": False, "message": "Quiz not found"}), 404
            cur.execute("DELETE FROM quizzes WHERE id = %s", (quiz_id,))
            conn.commit()
        return jsonify({"success": True, "message": "Quiz deleted"}), 200
    finally:
        conn.close()