FROM ubuntu:xenial

RUN apt-get update && apt-get -y install python3.5 python3-pip

RUN mkdir -p /src
ADD . /src

WORKDIR /src

RUN pip3 install --upgrade -r requirements.txt

EXPOSE 5000

CMD ["python3", "/src/nextbus.py"]
