# Go2 control environment — see INSTALL.md for the manual version of these steps.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GO2_NETWORK_INTERFACE=eno1 \
    CYCLONEDDS_HOME=/opt/cyclonedds/install

# git: clone the Unitree SDK & CycloneDDS (neither ships wheels on PyPI).
# build-essential/cmake: build CycloneDDS from source. libgl1/libglib2.0-0:
# runtime libs opencv-python needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        cmake \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# INSTALL.md step 3 — CycloneDDS has no PyPI wheel, so the C library must be
# built from source before the Python bindings can compile against it.
RUN git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x /opt/cyclonedds \
    && mkdir /opt/cyclonedds/build /opt/cyclonedds/install \
    && cd /opt/cyclonedds/build \
    && cmake .. -DCMAKE_INSTALL_PREFIX=../install \
    && cmake --build . --target install -- -j"$(nproc)"

# INSTALL.md step 4 — Unitree SDK, installed in editable mode.
RUN git clone https://github.com/unitreerobotics/unitree_sdk2_python.git /opt/unitree_sdk2_python \
    && pip install -e /opt/unitree_sdk2_python

# INSTALL.md step 5 — bridge & web app dependencies.
COPY requirements_bridge.txt .
RUN pip install -r requirements_bridge.txt

# INSTALL.md step 6 — MCP server dependencies.
RUN pip install "mcp[cli]"

# Project source.
COPY . .
RUN chmod +x entrypoint.sh

# INSTALL.md step 7 — verify installation.
RUN python -c "from unitree_sdk2py.go2.sport.sport_client import SportClient; print('SDK OK')" \
    && python -c "import zmq, fastapi, uvicorn; print('Bridge deps OK')"

# Needs the robot's network reachable, e.g.:
#   docker run --network host --env-file .env go2            # bridge (default)
#   docker run --network host --env-file .env go2 webapp
#   docker run --network host --env-file .env go2 mcp
#   docker run --network host --env-file .env go2 cli status
#   docker run --network host --env-file .env -it go2 bash
ENTRYPOINT ["./entrypoint.sh"]
CMD ["bridge"]
