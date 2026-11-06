FROM python:3.12-slim

ARG MINI_SWE_AGENT_REF=04d809ceab9df28f9adaed044884180159172930
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TIMEOUT=1200
ARG PIP_RETRIES=20

RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
      /etc/apt/sources.list.d/debian.sources \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
       bash \
       ca-certificates \
       curl \
       git \
       build-essential \
  && rm -rf /var/lib/apt/lists/*

RUN python -m pip install \
      --disable-pip-version-check \
      --prefer-binary \
      --timeout="${PIP_TIMEOUT}" \
      --retries="${PIP_RETRIES}" \
      --index-url="${PIP_INDEX_URL}" \
      "git+https://github.com/SWE-agent/mini-swe-agent.git@${MINI_SWE_AGENT_REF}"

# Skip mini-SWE-agent's interactive first-run setup in unattended workers.
ENV MSWEA_CONFIGURED=1

WORKDIR /workspace/repo

CMD ["mini", "--help"]
