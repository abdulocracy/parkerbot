FROM python:3

ENV PYTHONUNBUFFERED=1

WORKDIR /usr/src/app

COPY main.py requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

USER 1000:1000

CMD ["python", "./main.py"]
