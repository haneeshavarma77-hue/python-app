# Deploy with Jenkins on EC2 (GitHub → Jenkins → ECR → ECS)

Jenkins on an EC2 instance builds the Docker image (Flask :5000 + Streamlit :8501
via `supervisord`), pushes it to ECR, and deploys a new task definition revision
to the existing ECS service. This is the self-hosted alternative to CodeBuild and
GitHub Actions.

Pipeline definition: [`Jenkinsfile`](./Jenkinsfile) (Script Path
`ci/jenkins/Jenkinsfile`).

> The examples below use this repo's names — ECR repo `python-task-app`, cluster
> `python-task-cluster`, service `python-task-service`, task family `python-td`,
> container name `Main`. Change them to match your own resources (the container
> name **must** match `containerDefinitions[].name` in your task definition).

## 1. Architecture flow

```
 Developer
    │ git push (main)
    ▼
 GitHub ── webhook (POST /github-webhook/) ──┐
                                             ▼
                          EC2: Jenkins (ap-south-1)
                          IAM instance role (no access keys)
                             │
                             ├─ Checkout
                             ├─ docker build
                             ├─ docker push ───────────► ECR python-task-app:<sha>
                             └─ Deploy
                                 ├─ describe-task-definition
                                 ├─ swap image → register new revision
                                 ├─ update-service
                                 └─ wait services-stable
                                             │
                                             ▼
                          ECS Service (Fargate, rolling)
                                             │
              ALB ── /api/* → tg-api :5000 ──┤
                  └─ default → tg-ui :8501 ──┘
```

## 2. IAM role for the Jenkins EC2 instance

Use an **instance role**. Never put access keys on the server.

IAM → Roles → Create role → AWS service → **EC2** → name it `jenkins-ec2-role`.
Attach `AmazonSSMManagedInstanceCore` (so you can use Session Manager instead of
SSH), then add this inline policy `jenkins-ecr-ecs-deploy`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "EcrPush",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "arn:aws:ecr:ap-south-1:<ACCOUNT_ID>:repository/python-task-app"
    },
    {
      "Sid": "EcsDeploy",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition",
        "ecs:UpdateService",
        "ecs:DescribeServices"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassTaskRoles",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/ecsTaskExecutionRole",
      "Condition": {
        "StringEquals": { "iam:PassedToService": "ecs-tasks.amazonaws.com" }
      }
    }
  ]
}
```

If your task definition also has a **task role**, add its ARN to the
`PassTaskRoles` resource.

## 3. Launch the EC2 instance

EC2 → **Launch instance**

| Setting | Value |
|---|---|
| Name | `jenkins-server` |
| AMI | **Amazon Linux 2023** (x86_64) |
| Type | `t3.medium` (2 vCPU / 4 GB), the minimum for Docker builds |
| Key pair | Optional if you use Session Manager |
| Subnet | Public subnet (so GitHub webhooks can reach it) |
| Storage | **30 GB gp3** (Docker images fill disk fast) |
| IAM instance profile | `jenkins-ec2-role` |

**Security group `jenkins-sg`:**

| Port | Source | Why |
|---|---|---|
| 8080 | **Your IP only** | Jenkins UI |
| 8080 | GitHub webhook ranges (from `https://api.github.com/meta`, `hooks` list) | Webhooks |
| 22 | Your IP (skip if using Session Manager) | SSH |

Never open 8080 to `0.0.0.0/0`. For production, put Jenkins behind an ALB with
HTTPS. Assign an **Elastic IP** so the webhook URL doesn't change after a
stop/start.

## 4. Install Jenkins, Docker, Git, AWS CLI, jq

Connect via Session Manager (EC2 → Connect → Session Manager) or SSH, then run:

```bash
# Base packages (AWS CLI v2 is preinstalled on AL2023)
sudo dnf update -y
sudo dnf install -y java-21-amazon-corretto fontconfig git docker jq

# Jenkins LTS repo
sudo wget -O /etc/yum.repos.d/jenkins.repo https://pkg.jenkins.io/redhat-stable/jenkins.repo
sudo rpm --import https://pkg.jenkins.io/redhat-stable/jenkins.io-2023.key
sudo dnf install -y jenkins

# Let the jenkins user run docker
sudo usermod -aG docker jenkins

# Start services
sudo systemctl enable --now docker
sudo systemctl enable --now jenkins
sudo systemctl restart jenkins   # picks up docker group membership

# Verify
java -version
docker --version
aws --version
sudo -u jenkins docker ps                       # must NOT say permission denied
sudo -u jenkins aws sts get-caller-identity     # must show jenkins-ec2-role
```

> If `dnf install jenkins` fails with a **NOKEY / GPG** error, the Jenkins
> project has rotated its signing key. Get the current key URL from the official
> page (jenkins.io → Installing Jenkins → Linux → Red Hat) and re-run the
> `rpm --import`.

Get the initial admin password:

```bash
sudo cat /var/lib/jenkins/secrets/initialAdminPassword
```

## 5. Jenkins first-time setup (UI)

1. Open `http://<ELASTIC_IP>:8080`, paste the admin password, and choose
   **Install suggested plugins**.
2. Create an admin user. Set the Jenkins URL to `http://<ELASTIC_IP>:8080/`.
3. Manage Jenkins → **Plugins** → Available — make sure these are installed:
   **Pipeline**, **Git**, **GitHub** (provides the webhook trigger),
   **Timestamper**, and optionally **Pipeline: Stage View**.
4. Manage Jenkins → **Security** — keep "Logged-in users can do anything" with
   **Allow anonymous read access OFF**.

**GitHub credential (private repo):**

1. In GitHub: Settings → Developer settings → **Fine-grained token**. Grant this
   repo Contents: Read-only and Metadata: Read-only.
2. In Jenkins: Manage Jenkins → **Credentials** → System → Global →
   **Add credentials**:
   - Kind: **Username with password**
   - Username: your GitHub username
   - Password: the token
   - ID: `github-creds`

You don't need AWS credentials in Jenkins; the instance role handles AWS access.

## 6. The Jenkinsfile

[`Jenkinsfile`](./Jenkinsfile) defines the pipeline: checkout → resolve the ECR
registry → login → build & push → **prepare task definition** → deploy.

The "Prepare task definition" stage does **not** read a template from the repo.
It pulls the current task definition **live from ECS** by family
(`aws ecs describe-task-definition --task-definition python-td`), swaps the image
for the `Main` container with `jq`, and strips the read-only fields
(`taskDefinitionArn`, `revision`, `status`, `requiresAttributes`,
`compatibilities`, `registeredAt`, `registeredBy`, `deregisteredAt`) that
`register-task-definition` rejects. The deploy stage then registers the new
revision, runs `aws ecs update-service`, and `aws ecs wait services-stable`.

Because the task definition comes from ECS, there's **no task-def JSON file to
maintain in the repo** and no `envsubst` step — only `docker`, `aws` CLI v2, and
`jq` are needed on the agent. The wait polls for up to ~10 minutes; if the ECS
**deployment circuit breaker with rollback** is enabled, a bad image rolls back
automatically and fails the build.

> The task family `python-td` must already exist in ECS before the first run
> (create it once when you set up the cluster/service). The pipeline reads and
> revises it; it never creates the family from scratch.

## 7. Create the pipeline job

Jenkins → **New Item** → name it `python-task-app` → **Pipeline** → OK.

- **Triggers:** check **GitHub hook trigger for GITScm polling**.
- **Pipeline:**
  - Definition: **Pipeline script from SCM**
  - SCM: Git
  - Repository URL: `https://github.com/<org>/python-app.git`
  - Credentials: `github-creds`
  - Branch: `*/main`
  - Script Path: `ci/jenkins/Jenkinsfile`

Save, then **Build Now** once. The first run registers the webhook trigger.

## 8. GitHub webhook

GitHub repo → Settings → **Webhooks** → Add webhook

| Field | Value |
|---|---|
| Payload URL | `http://<ELASTIC_IP>:8080/github-webhook/` (trailing slash required) |
| Content type | `application/json` |
| Events | Just the push event |

After saving, open Recent Deliveries and look for a green tick with a 200 response.

## 9. Verify end to end

1. Push a small change to `main`.
2. The Jenkins job starts automatically and all stages turn green.
3. In ECR, a new tag matching the commit's short SHA appears.
4. In ECS → Service → Deployments, the new task revision shows PRIMARY → COMPLETED.
5. In a browser: `http://<ALB-DNS>/` → Streamlit, `http://<ALB-DNS>/api/health`
   (or `:5000/health`) → healthy.

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `permission denied ... /var/run/docker.sock` | `sudo usermod -aG docker jenkins && sudo systemctl restart jenkins` |
| `Unable to locate credentials` | Instance profile not attached. EC2 → Actions → Security → Modify IAM role. |
| `AccessDenied ... iam:PassRole` | Add the execution/task role ARNs to `PassTaskRoles` in the instance policy. |
| `jq: command not found` | `sudo dnf install -y jq` |
| Webhook timeout / failed delivery | SG 8080 not open to GitHub hook IPs, URL missing trailing `/github-webhook/`, or the IP changed (use an Elastic IP). |
| Job doesn't trigger on push | Run the job manually once; confirm "GitHub hook trigger for GITScm polling" is ticked. |
| `no space left on device` | Increase the EBS volume, or run `docker system prune -af`. |
| `register-task-definition` unknown parameter | A new read-only field from describe output; strip it before registering. |
| `services-stable` times out | Tasks failing health checks. Check CloudWatch logs and target group health. |
| Jenkins UI slow / builds OOM | Move to `t3.large`, or add swap. |

## 11. Hardening (recommended next)

- Put Jenkins behind an **ALB + ACM HTTPS** and remove public 8080.
- Back up `/var/lib/jenkins` with EBS snapshots / AWS Backup.
- Keep executors low (1–2); move builds to separate or ephemeral agents later.
- Add an **ECR lifecycle policy** to keep the last ~20 images.
- Enable the **ECS deployment circuit breaker** with rollback.
- Keep plugins and the OS patched (`dnf upgrade`).

---

## Variation — Jenkins as orchestrator, CodeBuild as the build provider

In the setup above, the Docker image is built **on the Jenkins EC2 instance's own
Docker daemon**. That means the EC2 box needs enough CPU, RAM, and disk for every
build, and concurrent builds compete for it.

An alternative: keep Jenkins as the **orchestrator** (trigger, approvals, stage
view, notifications) but hand the heavy `docker build` to **AWS CodeBuild**.
Jenkins just starts a CodeBuild run that uses
[`../codebuild/buildspec.yml`](../codebuild/buildspec.yml), waits for it to
finish, then deploys to ECS. This is the common pattern when you want Jenkins'
control plane without maintaining a build fleet.

```
 GitHub ──webhook──► Jenkins (EC2, small t3.small is fine)
                        │ start-build
                        ▼
                   AWS CodeBuild  ──uses──► buildspec.yml
                        │ build + push image
                        ▼
                   ECR python-task-app:<sha>
                        ▲
                        │ (Jenkins waits for build to succeed)
 Jenkins ──deploy──► ECS update-service + wait services-stable
```

### Why do this

- The Jenkins instance can be tiny — it no longer builds Docker images, so it
  needs no privileged daemon and little disk.
- CodeBuild gives clean, isolated, ephemeral build environments per run and
  scales to many concurrent builds.
- You reuse the **same `ci/codebuild/buildspec.yml`** the pure-CodeBuild path
  uses, so there's one source of truth for how the image is built.

### One-time setup

1. **Create a CodeBuild project** (console or CLI) named `python-task-app-build`:
   - Source: your GitHub repo (or "No source" if Jenkins supplies the source via
     `sourceVersion`).
   - Environment: Amazon Linux managed image, **Privileged** enabled (required to
     build Docker images), with the CodeBuild service role granted ECR push +
     `sts:GetCallerIdentity`.
   - Buildspec: set the buildspec path to `ci/codebuild/buildspec.yml`.
2. **Grant Jenkins permission to drive CodeBuild.** Add to the
   `jenkins-ec2-role` instance policy:

   ```json
   {
     "Sid": "StartCodeBuild",
     "Effect": "Allow",
     "Action": [
       "codebuild:StartBuild",
       "codebuild:BatchGetBuilds"
     ],
     "Resource": "arn:aws:codebuild:ap-south-1:<ACCOUNT_ID>:project/python-task-app-build"
   }
   ```

   Jenkins no longer needs `ecr:*` push permissions in this model — CodeBuild's
   own service role pushes the image. Jenkins keeps only the `ecs:*` and
   `iam:PassRole` permissions for the deploy stage.

### Replace the build stages in the Jenkinsfile

Swap the local `docker build` / `docker push` stages for a stage that starts
CodeBuild and waits for it. Two ways:

**Option 1 — AWS CLI (no plugin):**

```groovy
stage('Build via CodeBuild') {
  steps {
    sh '''
      set -e
      BUILD_ID=$(aws codebuild start-build \
        --project-name python-task-app-build \
        --source-version "$GIT_COMMIT" \
        --region "$AWS_REGION" \
        --query 'build.id' --output text)
      echo "Started CodeBuild: $BUILD_ID"

      # Poll until the build leaves IN_PROGRESS
      while true; do
        STATUS=$(aws codebuild batch-get-builds --ids "$BUILD_ID" \
          --region "$AWS_REGION" \
          --query 'builds[0].buildStatus' --output text)
        echo "CodeBuild status: $STATUS"
        [ "$STATUS" = "IN_PROGRESS" ] || break
        sleep 15
      done

      [ "$STATUS" = "SUCCEEDED" ] || { echo "CodeBuild failed: $STATUS"; exit 1; }
    '''
  }
}
```

**Option 2 — AWS CodeBuild Jenkins plugin:** install "AWS CodeBuild" from
Manage Jenkins → Plugins, then use the `awsCodeBuild` step with your project
name. The plugin streams CodeBuild logs into the Jenkins console and fails the
stage automatically on a non-`SUCCEEDED` result.

The **Deploy to ECS** stage stays exactly as in the main section — it reads the
image tag (the commit SHA) that CodeBuild just pushed and rolls the service.

### Trade-offs

| | Jenkins builds locally | Jenkins → CodeBuild |
|---|---|---|
| Jenkins instance size | `t3.medium`+ (needs Docker) | `t3.small` is fine |
| Privileged Docker on Jenkins | Required | Not needed |
| Build isolation | Shared daemon | Fresh env per build |
| Concurrent builds | Limited by one box | Scales in CodeBuild |
| Extra cost | None beyond EC2 | CodeBuild per-minute billing |
| Moving parts | Fewer | More (two services to wire) |
