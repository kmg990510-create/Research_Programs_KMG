FROM python:3.11-slim

RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR $HOME/app

COPY --chown=user:user MoS2_optical_analysis/requirements.txt /tmp/requirements.txt
RUN grep -v -E "^(PySide6|pyqtgraph)" /tmp/requirements.txt > /tmp/requirements-web.txt && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements-web.txt

COPY --chown=user:user MoS2_optical_analysis/ $HOME/app/
RUN mkdir -p $HOME/app/data/raw/raman $HOME/app/data/raw/pl $HOME/app/data/results/raman/reports $HOME/app/data/results/pl/reports && \
    chown -R user:user $HOME/app

USER user
EXPOSE 7860

CMD ["streamlit", "run", "gui/Main.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.maxUploadSize=500"]
