from flask import Flask, jsonify, request
from datetime import datetime

app = Flask(__name__)

# In-memory store for demo purposes
tasks = []
task_id_counter = 1


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Welcome to the Python Task API!",
        "version": "1.0.0",
        "endpoints": {
            "GET  /": "This help message",
            "GET  /health": "Health check",
            "GET  /tasks": "List all tasks",
            "POST /tasks": "Create a new task",
            "GET  /tasks/<id>": "Get a task by ID",
            "PATCH /tasks/<id>": "Update a task (done, title, description)",
            "DELETE /tasks/<id>": "Delete a task by ID",
        }
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })


@app.route("/tasks", methods=["GET"])
def get_tasks():
    return jsonify({"tasks": tasks, "count": len(tasks)})


@app.route("/tasks", methods=["POST"])
def create_task():
    global task_id_counter
    data = request.get_json()

    if not data or "title" not in data:
        return jsonify({"error": "Request body must include a 'title' field"}), 400

    task = {
        "id": task_id_counter,
        "title": data["title"],
        "description": data.get("description", ""),
        "done": False,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    tasks.append(task)
    task_id_counter += 1

    return jsonify(task), 201


@app.route("/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id):
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        return jsonify({"error": f"Task {task_id} not found"}), 404
    return jsonify(task)


@app.route("/tasks/<int:task_id>", methods=["PATCH"])
def update_task(task_id):
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        return jsonify({"error": f"Task {task_id} not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body must be a JSON object"}), 400

    if "done" in data:
        if not isinstance(data["done"], bool):
            return jsonify({"error": "'done' must be a boolean"}), 400
        task["done"] = data["done"]
    if "title" in data:
        if not str(data["title"]).strip():
            return jsonify({"error": "'title' cannot be empty"}), 400
        task["title"] = data["title"]
    if "description" in data:
        task["description"] = data["description"]

    return jsonify(task)


@app.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    global tasks
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        return jsonify({"error": f"Task {task_id} not found"}), 404
    tasks = [t for t in tasks if t["id"] != task_id]
    return jsonify({"message": f"Task {task_id} deleted successfully"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
