# Python Task Manager

A full-stack task manager: a **Flask REST API** backend + a **Streamlit** frontend, both Dockerized and wired together with Docker Compose.

## Architecture

```
Browser → Streamlit UI (port 8501)
               ↓  HTTP
          Flask API  (port 5000)
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API overview |
| GET | `/health` | Health check |
| GET | `/tasks` | List all tasks |
| POST | `/tasks` | Create a task (`{"title": "...", "description": "..."}`) |
| GET | `/tasks/<id>` | Get task by ID |
| DELETE | `/tasks/<id>` | Delete task by ID |

---

## Run with Docker Compose (recommended)

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Streamlit UI | http://localhost:8501 |
| Flask API | http://localhost:5000 |

## Run locally (without Docker)

**Terminal 1 – API:**
```bash
pip install -r requirements.txt
python app.py
```

**Terminal 2 – Frontend:**
```bash
pip install -r frontend/requirements.txt
streamlit run frontend/streamlit_app.py
```

## Example Usage

```bash
# Create a task
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Buy groceries", "description": "Milk, eggs, bread"}'

# List tasks
curl http://localhost:5000/tasks

# Get a specific task
curl http://localhost:5000/tasks/1

# Delete a task
curl -X DELETE http://localhost:5000/tasks/1
```

---

## Deploy to AWS ECS (single combined image)

For production, the app ships as **one Docker image** that runs both the Flask
API (port 5000) and the Streamlit UI (port 8501), supervised by `supervisord`.
This keeps it to a single ECR repo and a single ECS task.

```
ECS Task (Fargate)
└── python-task-app container
    ├── gunicorn  → :5000  (Flask API)
    └── streamlit → :8501  (UI, talks to API at http://localhost:5000)
```

### Build/run the combined image locally

```bash
docker build -t python-task-app .
docker run -p 5000:5000 -p 8501:8501 python-task-app
# UI:  http://localhost:8501
# API: http://localhost:5000
```

### Shared files

| File | Purpose |
|------|---------|
| `Dockerfile` | Single combined image (Flask + Streamlit) |
| `deploy/supervisord.conf` | Runs both processes in the container |
| `deploy/ecs-task-definition.json` | Fargate task definition template |

How you ship that image to ECS is up to you — pick a CI/CD provider below.

---

## CI/CD Options (educational)

This repo intentionally ships several ways to build and deploy the same image,
so you can compare them. The first three are standalone; the last two are
variations on where the build actually runs.

| Option | File | Build runs on | Best for |
|--------|------|---------------|----------|
| AWS CodeBuild / CodePipeline | `ci/codebuild/buildspec.yml` | AWS-managed build | Staying fully inside AWS |
| GitHub Actions (hosted) | `.github/workflows/deploy.yml` | GitHub-hosted runners | GitHub-native, OIDC, no servers to manage |
| Jenkins on EC2 | `ci/jenkins/Jenkinsfile` | The Jenkins EC2 Docker daemon | Self-hosted control, on-prem parity |
| **Jenkins → CodeBuild** | `ci/jenkins/Jenkinsfile` + `ci/codebuild/buildspec.yml` | AWS CodeBuild (triggered by Jenkins) | Jenkins orchestration without a build fleet |
| **GitHub Actions self-hosted runner** | `.github/workflows/deploy.yml` | Your own runner (e.g. EC2) | Private networking, custom build hardware |

All of them produce the same result: build the single combined image, push it to
ECR, register a new ECS task definition revision, and roll out the service.
They differ only in **who orchestrates** and **where the Docker build executes**.

### Per-provider setup guides

Each provider has its own folder with the config file **and** a full setup guide:

| Provider | Config | Guide |
|----------|--------|-------|
| AWS CodeBuild | `ci/codebuild/buildspec.yml` | [`ci/codebuild/README.md`](ci/codebuild/README.md) |
| Jenkins on EC2 (+ Jenkins→CodeBuild) | `ci/jenkins/Jenkinsfile` | [`ci/jenkins/README.md`](ci/jenkins/README.md) |
| GitHub Actions (+ self-hosted runner) | `.github/workflows/deploy.yml` | [`ci/github-actions/README.md`](ci/github-actions/README.md) |

### Where the CI/CD files live

```
python-app/
├── ci/
│   ├── codebuild/
│   │   ├── buildspec.yml        # AWS CodeBuild build spec
│   │   └── README.md            # CodeBuild setup guide
│   ├── jenkins/
│   │   ├── Jenkinsfile          # Jenkins pipeline
│   │   └── README.md            # Jenkins setup guide (+ Jenkins→CodeBuild)
│   └── github-actions/
│       └── README.md            # GitHub Actions setup guide (+ self-hosted runner)
└── .github/
    └── workflows/
        └── deploy.yml           # GitHub Actions workflow (must stay here — GitHub
                                 #   only discovers workflows under .github/workflows/)
```

`Dockerfile` and `docker-compose.yml` stay at the repo root because they're the
shared build definition every pipeline (and local dev) uses. The CI configs use a
build context of `.` and paths relative to the repo root, so they keep working
from their folders — CI systems check out the whole repo and run from the root.

The GitHub Actions **workflow YAML** must stay in `.github/workflows/`; only its
documentation lives under `ci/github-actions/`.
