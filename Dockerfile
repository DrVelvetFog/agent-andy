# Check Agent Andy in a clean box: the offline test suite, then the recorded
# 33-receipt chain and its signature. No key, no network, no pip install.
# It does not serve the viewer, which binds 127.0.0.1 only.
FROM python:3.12-slim
# ssh-keygen verifies the chain signature; git and pgrep/pkill are used by the tests.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client procps \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /andy
COPY . .
CMD ["sh", "-c", "python3 -m unittest discover tests && python3 scripts/verify_receipts.py docs/replay/live-demo-chain.jsonl --expect-count 33 --require-signature"]
