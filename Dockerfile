FROM python:3.11.17-slim-trixie

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Refresh Debian security fixes, including the system roots used by IMAP/urllib.
# Fail closed if the mirror has not published the incident remediation.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge '20250419+deb13u1' \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Official Python advisory bootstrap: old pip must verify the trusted SHA256.
# Do this before resolving any other Python packages.
RUN python -m pip --isolated install --no-cache-dir --no-deps \
    'pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70'

# setuptools is unused at runtime and the base's bundled version has advisories.
RUN python -m pip uninstall -y setuptools

COPY requirements.txt /app/requirements.txt
RUN python -m pip --isolated install --no-cache-dir --require-hashes -r /app/requirements.txt \
    && python -m pip check

COPY scripts/verify_trust.py /app/scripts/verify_trust.py
RUN python /app/scripts/verify_trust.py

COPY app /app/app
COPY migrations /app/migrations
COPY SPEC.md /app/SPEC.md
COPY TASKS.md /app/TASKS.md
COPY README.md /app/README.md

CMD ["python", "-m", "app.cmd.main"]
