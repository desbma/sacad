FROM python:3-alpine
RUN apk update
RUN apk add optipng jpegoptim
RUN python -m pip install --upgrade pip
RUN pip3 install sacad
RUN mkdir /music
WORKDIR /music
CMD [ "cd", "/music" ]