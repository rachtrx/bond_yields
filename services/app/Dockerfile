# Builder stage
FROM condaforge/mambaforge:latest as builder

WORKDIR /usr/src/app

# Copy environment file and create environment
COPY environment.yml .
RUN mamba env create -f environment.yml

# Final stage
FROM condaforge/mambaforge:latest

# create directory for the app user
RUN mkdir -p /home/app

# Copy environment from builder stage
COPY --from=builder /opt/conda/envs/bonds /opt/conda/envs/bonds

# Adjust PATH to activate the conda environment
ENV PATH /opt/conda/envs/bonds/bin:$PATH

ENV DEBIAN_FRONTEND noninteractive

# Install system utilities required for subsequent operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    postgresql-client \
    cron \
    gnupg2 \
    ca-certificates \
    supervisor \
    libnss3-tools \
    jq \
    tar \
    firefox \
    && rm -rf /var/lib/apt/lists/*

RUN mitmdump --quiet & sleep 10; kill $!

COPY . /home/app

WORKDIR /home/app

RUN chmod +x entrypoint.sh

# Fetch and install the latest Geckodriver
RUN GECKODRIVER_URL=$(curl -s https://api.github.com/repos/mozilla/geckodriver/releases/latest | jq -r '.assets[].browser_download_url | select(endswith("linux64.tar.gz"))') \
    && curl -L "$GECKODRIVER_URL" | tar -xz -C /usr/local/bin

# ENV DISPLAY=:99

COPY others/bonds_sync.txt /etc/cron.d/bonds_sync.txt

# Give execution rights on the cron job
RUN chmod 0644 /etc/cron.d/bonds_sync.txt

# Apply cron job
RUN crontab /etc/cron.d/bonds_sync.txt
 
# Create the log file to be able to run tail
RUN touch /var/log/cron_daily.log
RUN touch /var/log/cron_realtime.log

COPY others/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

ENTRYPOINT ["/home/app/entrypoint.sh"]
