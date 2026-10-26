# Deploying NutriWise on AWS EC2

Topology: Internet → Caddy (80/443, automatic TLS) → Gunicorn/Flask (8080, internal Docker network only) → BGE + FAISS on CPU, DeepSeek API for generation. Redis is internal and only stores rate-limit counters.

This guide targets a new AWS account on the Free plan in `us-east-1`. It uses `sslip.io`, a public wildcard DNS service that resolves `203-0-113-10.sslip.io` to `203.0.113.10`, so Let's Encrypt can issue a real certificate without buying a domain.

## 0. Before you start

- CI on `main` is green.
- You have the three private index files (`index.faiss`, `index.pkl`, `manifest.json`); see [vector_store/README.md](vector_store/README.md).
- You have a DeepSeek API key dedicated to this deployment, with a small prepaid balance.
- In the AWS console: MFA is enabled on the root user, and a monthly cost budget with email alerts exists (Billing and Cost Management → Budgets).

## 1. Launch the instance

EC2 → Launch instance:

| Setting | Value |
| --- | --- |
| AMI | Ubuntu Server 24.04 LTS, 64-bit (x86) |
| Instance type | `c7i-flex.large` (2 vCPU, 4 GiB). Use `m7i-flex.large` (8 GiB) if memory is tight. |
| Key pair | Create a new RSA key pair and download the `.pem` file |
| Storage | 30 GiB gp3 |
| Security group | Inbound: TCP 22 from **My IP**, TCP 80 and TCP 443 from `0.0.0.0/0` |

Do not open 8080 or 6379; they are reachable only inside the Docker network.

## 2. Attach an Elastic IP

EC2 → Elastic IPs → Allocate Elastic IP address → Actions → Associate → select the instance.

A fixed address matters because the hostname is derived from it; without one, the IP (and therefore the URL and certificate) changes whenever the instance is stopped and started. Write down the address, e.g. `203.0.113.10`. The hostname is the same address with dashes: `203-0-113-10.sslip.io`.

## 3. Connect

```bash
chmod 400 nutriwise.pem
ssh -i nutriwise.pem ubuntu@203.0.113.10
```

## 4. Add swap

The image build and the 1.3 GB embedding model leave little headroom on 4 GiB. Swap prevents out-of-memory kills; it is not a substitute for RAM.

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-nutriwise.conf
sudo sysctl --system
free -h
```

## 5. Install Docker Engine and the Compose plugin

From Docker's official apt repository:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

The commands below use `sudo docker` rather than adding the login user to the `docker` group, which is equivalent to root access.

## 6. Get the code and the private index

On the instance:

```bash
sudo mkdir -p /opt/nutriwise && sudo chown ubuntu:ubuntu /opt/nutriwise
git clone https://github.com/Yimeng0824/NutriWise.git /opt/nutriwise
```

From your own machine, copy the index (it never goes through GitHub):

```bash
scp -i nutriwise.pem index.faiss index.pkl manifest.json ubuntu@203.0.113.10:/opt/nutriwise/vector_store/
```

## 7. Configure

```bash
cd /opt/nutriwise
cp .env.example .env
chmod 600 .env
nano .env
```

Set at least:

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<your key>
MAX_TOKENS=1200
ASK_LIMIT=10/minute;100/day
DOMAIN=203-0-113-10.sslip.io
```

## 8. Build and start

The first build downloads PyTorch (CPU) and the pinned BGE weights and takes several minutes.

```bash
cd /opt/nutriwise
sudo docker compose config --quiet
sudo docker compose build
sudo docker compose up -d
sudo docker compose ps
```

`app` reports `healthy` once Gunicorn is up; Caddy starts after that and requests the certificate. Logs:

```bash
sudo docker compose logs --tail=100 caddy   # look for "certificate obtained successfully"
sudo docker compose logs --tail=100 app
```

## 9. Verify

```bash
DOMAIN=203-0-113-10.sslip.io

# HTTPS with a publicly trusted certificate (no -k flag)
curl -fsS https://$DOMAIN/healthz
curl -v https://$DOMAIN/healthz 2>&1 | grep -E "issuer|SSL certificate verify ok"

# First call loads and verifies the model and index
curl -fsS --max-time 240 https://$DOMAIN/readyz

# Routes
bash scripts/smoke_public.sh $DOMAIN

# Streaming: tokens should arrive incrementally as "event: token" lines
curl -N -X POST https://$DOMAIN/student/api/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"question": "为什么要多吃蔬菜？"}'

# Resource usage after one question
sudo docker stats --no-stream
free -h
```

Then open `https://$DOMAIN/student/` and `https://$DOMAIN/teacher/` in a browser and ask a question in each.

## 10. Updates

```bash
cd /opt/nutriwise
git pull --ff-only
sudo docker compose build
sudo docker compose up -d
bash scripts/smoke_public.sh 203-0-113-10.sslip.io
```

Avoid `docker compose down -v`: `-v` deletes the Redis and Caddy volumes, including quota counters and certificates.

## 11. Cost notes

Approximate us-east-1 on-demand prices: `c7i-flex.large` about $62/month, 30 GiB gp3 about $2.40/month, one public IPv4 address about $3.65/month, so roughly $68/month in total. On the Free plan this is drawn from account credits; the account is suspended, not billed, when the credits run out. Stopping the instance stops compute charges, but storage and the Elastic IP keep billing. Release the Elastic IP and terminate the instance when the deployment is no longer needed.

Generation cost is bounded by `MAX_TOKENS`, `ASK_LIMIT` and `MAX_CONCURRENT`. CI uses mocks only and never calls the real API.
