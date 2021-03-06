FROM python:3.5

LABEL Author Oliver Bell <freshollie@gmail.com>

WORKDIR /opt/cashpassport-api

COPY setup.py setup.py

RUN python3 setup.py develop

COPY src src
