FROM ubuntu:xenial

RUN apt-get update && apt-get -y install python3.5 python3-pip

RUN mkdir -p /src
ADD . /src

WORKDIR /src

RUN pip3 install -r requirements.txt

CMD ["python3", "populator.py"]
