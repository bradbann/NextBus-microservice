FROM ubuntu:xenial

RUN apt-get update && apt-get -y install nano wget unzip dialog net-tools nginx

# Fetching and installing confd
WORKDIR /tmp
RUN wget -O confd https://github.com/kelseyhightower/confd/releases/download/v0.12.0-alpha3/confd-0.12.0-alpha3-linux-amd64
RUN chmod 755 confd
RUN mv confd /usr/sbin/
RUN mkdir -p /etc/confd/conf.d
RUN mkdir -p /etc/confd/templates
COPY nginx.toml /etc/confd/conf.d/nginx.toml
COPY nginx.conf.tmpl /etc/confd/templates/nginx.conf.tmpl
COPY confd-watch /usr/sbin/confd-watch

CMD /usr/sbin/confd-watch
