FROM python:3

ENV PYTHONUNBUFFERED=1

WORKDIR /usr/src/app

COPY main.py requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "./main.py"]