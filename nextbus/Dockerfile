FROM ubuntu:xenial

RUN apt-get update && apt-get -y install curl cron net-tools python3.5 python3-pip

RUN mkdir -p /src
ADD . /src

WORKDIR /src

RUN pip3 install --upgrade -r requirements.txt

EXPOSE 5000

ADD crontab /etc/cron.d/nextbus-cron
RUN /usr/bin/crontab /etc/cron.d/nextbus-cron

CMD sh start_nextbus.sh
