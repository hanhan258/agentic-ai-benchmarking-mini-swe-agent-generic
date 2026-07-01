FROM python:3.12-slim

ARG MINI_SWE_AGENT_REF=main

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash ca-certificates curl git build-essential \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "git+https://github.com/SWE-agent/mini-swe-agent.git@${MINI_SWE_AGENT_REF}"

WORKDIR /workspace/repo

CMD ["mini", "--help"]
