FROM python:3.11-slim

RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR $HOME/app

COPY --chown=user:user requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

COPY --chown=user:user .streamlit/ $HOME/app/.streamlit/
COPY --chown=user:user app.py $HOME/app/app.py
COPY --chown=user:user MoS2_optical_analysis/ $HOME/app/MoS2_optical_analysis/
COPY --chown=user:user FET_analysis/ $HOME/app/FET_analysis/
COPY --chown=user:user MoS2_adsorption_sim/ $HOME/app/MoS2_adsorption_sim/
# shared lab code (plot theme, sidebar sections, figure size); each program adds repo root to sys.path
COPY --chown=user:user labkit/ $HOME/app/labkit/
RUN mkdir -p \
    $HOME/app/MoS2_optical_analysis/data/raw/raman \
    $HOME/app/MoS2_optical_analysis/data/raw/pl \
    $HOME/app/MoS2_optical_analysis/data/results/raman/reports \
    $HOME/app/MoS2_optical_analysis/data/results/pl/reports \
    $HOME/app/FET_analysis/data/raw \
    $HOME/app/FET_analysis/data/results \
    $HOME/app/FET_analysis/data/outputs \
    $HOME/app/MoS2_adsorption_sim/data/raw \
    $HOME/app/MoS2_adsorption_sim/data/results \
    $HOME/app/MoS2_adsorption_sim/data/outputs && \
    chown -R user:user $HOME/app

USER user
EXPOSE 7860

CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.maxUploadSize=500"]
