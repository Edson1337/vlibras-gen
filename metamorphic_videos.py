import cv2
import os
import numpy as np


def mudar_iluminacao(frame, fator=1.5, gamma=None):
    
    """
    Altera a luminosidade de um frame de forma mais robusta.

    Args:
        frame:    Frame BGR (uint8)
        fator:    Multiplicador de brilho (1.0 = original, >1 clareia, <1 escurece)
        gamma:    Se fornecido, aplica correção gamma (0.5 clareia, 2.0 escurece)
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2].astype(np.float32)  # ← evita overflow de uint8
    v = np.clip(v * fator, 0, 255)

    # Correção gamma (opcional) — mais perceptualmente uniforme que escala linear
    if gamma is not None:
        v = np.power(v / 255.0, gamma) * 255.0

    hsv[:, :, 2] = v.astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

def adicionar_ruido(frame, intensidade=25, tipo="gaussiano", por_canal=True, seed=None):
    """
    Adiciona ruído a um frame de vídeo.

    Args:
        frame:      Frame BGR (uint8)
        intensidade: Força do ruído (0–255)
        tipo:       "gaussiano" | "sal_pimenta" | "poisson" | "speckle"
        por_canal:  Se True, gera ruído independente por canal (mais realista)
        seed:       Semente para reprodutibilidade
    """
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()

    frame_f = frame.astype(np.float32)
    shape = frame.shape if por_canal else frame.shape[:2]

    if tipo == "gaussiano":
        ruido = rng.normal(0, intensidade, frame.shape if por_canal else (*frame.shape[:2], 1))
        if not por_canal:
            ruido = np.repeat(ruido, 3, axis=2)
        resultado = frame_f + ruido

    elif tipo == "sal_pimenta":
        resultado = frame_f.copy()
        densidade = intensidade / 255.0  # intensidade vira probabilidade
        mascara = rng.random(frame.shape[:2])

        resultado[mascara < densidade / 2] = 0      # pimenta
        resultado[mascara > 1 - densidade / 2] = 255  # sal

    elif tipo == "poisson":
        # Ruído que escala com o brilho — simula sensores reais
        escala = intensidade / 10.0
        resultado = rng.poisson(frame_f / escala + 1e-6) * escala

    elif tipo == "speckle":
        # Ruído multiplicativo — comum em imagens de radar/ultrassom
        ruido = rng.normal(0, intensidade / 255.0, frame.shape)
        resultado = frame_f + frame_f * ruido

    else:
        raise ValueError(f"Tipo de ruído inválido: '{tipo}'. Use: gaussiano, sal_pimenta, poisson, speckle")

    return np.clip(resultado, 0, 255).astype(np.uint8)

def rotacionar_frame(frame, angulo=5, interpolacao=cv2.INTER_LINEAR):
    """
    Rotaciona um frame simples, mantendo tamanho original.
    Bordas pretas são esperadas e aceitas.

    Args:
        frame:        Frame BGR (uint8)
        angulo:       Ângulo em graus (positivo = anti-horário)
        interpolacao: INTER_NEAREST → mais rápido (tempo real)
                      INTER_LINEAR  → equilibrado (padrão)
                      INTER_CUBIC   → mais suave (pós-processamento)
    """
    altura, largura = frame.shape[:2]
    centro = (largura / 2, altura / 2)  # float em vez de // para maior precisão

    matriz = cv2.getRotationMatrix2D(centro, angulo, 1.0)
    return cv2.warpAffine(frame, matriz, (largura, altura), flags=interpolacao)

def frame_dropping(frame, probabilidade=0.1, repetir_ultimo=True):
    """
    Simula travamento de vídeo repetindo o último frame válido.

    Args:
        frame:          Frame atual (uint8)
        probabilidade:  Chance de "travar" (0.0 a 1.0)
        repetir_ultimo: Se True, repete o último frame (travamento real)
                        Se False, retorna None (frame ausente)
    """
    if not hasattr(frame_dropping, "ultimo_frame"):
        frame_dropping.ultimo_frame = frame.copy()

    if np.random.rand() < probabilidade:
        if repetir_ultimo:
            return frame_dropping.ultimo_frame  # repete o frame anterior
        return None

    frame_dropping.ultimo_frame = frame.copy()
    return frame

def acelerar_video(frame, frame_atual, fator=2.0):
    """
    Acelera o vídeo pulando frames proporcionalmente ao fator.

    Args:
        frame:       Frame atual (uint8)
        frame_atual: Índice do frame no vídeo original
        fator:       Fator de aceleração (ex: 2.0 = dobro da velocidade)
                     Aceita valores fracionários (ex: 1.5, 3.7)
    """
    if fator <= 0:
        raise ValueError("fator deve ser maior que zero")
    if fator < 1.0:
        raise ValueError("para desacelerar, use uma função de interpolação")

    # Acumula erro fracionário para distribuir os frames uniformemente
    if not hasattr(acelerar_video, "acumulador"):
        acelerar_video.acumulador = 0.0

    acelerar_video.acumulador += 1.0 / fator

    if acelerar_video.acumulador >= 1.0:
        acelerar_video.acumulador -= 1.0
        return frame

    return None


## Crie as pastas "lighting", "fast_motion","frame_drops","noise","rotation", e "videos" dentro do projeto 
## ou mude os caminhos abaixo para algum escolhido

output_path_lighting = "lighting"
output_path_fast_motion = "fast_motion"
output_path_frame_drop = "frame_drops"
output_path_noise = "noise"
output_path_rotation = "rotation"

input_path = "videos"


name_videos = os.listdir(input_path)

## lighting videos

for name in name_videos:

    video = cv2.VideoCapture(f"{input_path}/{name}")

    fps = video.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30

    ret, frame = video.read()
    if not ret:
        continue

    H, W = frame.shape[:2]

    name_mp4 = os.path.splitext(name)[0] + ".mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')

    out = cv2.VideoWriter(f"{output_path_lighting}/{name_mp4}", fourcc, fps, (W, H))

    if not out.isOpened():
        print("Erro ao criar vídeo:", name)
        continue

    while True:
        video_ = mudar_iluminacao(frame, 0.05)
        out.write(video_)

        cv2.imshow("Video", video_)
        if cv2.waitKey(25) & 0xFF == ord('q'):
            break

        ret, frame = video.read()
        if not ret:
            break

    video.release()
    out.release()
    cv2.destroyAllWindows()

## fast_motion videos

for name in name_videos:
    video = cv2.VideoCapture(f"{input_path}/{name}")

    fps = video.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30

    ret, frame = video.read()
    if not ret:
        continue

    H, W = frame.shape[:2]

    fator = 4

    name_out = os.path.splitext(name)[0] + ".mp4"
    fourcc = cv2.VideoWriter_fourcc(*'XVID')

    out = cv2.VideoWriter(f"{output_path_fast_motion}/{name_out}", fourcc, fps * fator, (W, H))

    if not out.isOpened():
        print("Erro ao criar vídeo:", name)
        continue

    frame_count = 0

    while True:
        video_ = acelerar_video(frame, frame_count, fator=fator)

        if video_ is not None:
            out.write(video_)
            cv2.imshow("Video", video_)

        frame_count += 1

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        ret, frame = video.read()
        if not ret:
            break

    video.release()
    out.release()
    cv2.destroyAllWindows()

## frame drop videos 

for name in name_videos:
    
    video = cv2.VideoCapture(f"{input_path}/{name}")

    fps = video.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30

    ret, frame = video.read()
    if not ret:
        continue

    H, W = frame.shape[:2]

    name_out = os.path.splitext(name)[0] + ".mp4"
    fourcc = cv2.VideoWriter_fourcc(*'XVID')

    out = cv2.VideoWriter(f"{output_path_frame_drop}/{name_out}", fourcc, fps, (W, H))

    if not out.isOpened():
        print("Erro ao criar vídeo:", name)
        continue

    ultimo_frame_valido = None

    while True:
        video_ = frame_dropping(frame, 0.3)

        if video_ is not None:
            ultimo_frame_valido = video_
        else:
            video_ = ultimo_frame_valido

        if video_ is not None:
            out.write(video_)
            cv2.imshow("Video", video_)

        if cv2.waitKey(25) & 0xFF == ord('q'):
            break

        ret, frame = video.read()
        if not ret:
            break

    video.release()
    out.release()
    cv2.destroyAllWindows()  

## noise videos


for name in name_videos:
    
    video = cv2.VideoCapture(f"{input_path}/{name}")

    fps = video.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30

    ret, frame = video.read()
    if not ret:
        continue

    H, W = frame.shape[:2]

    # força compatibilidade
    name_avi = os.path.splitext(name)[0] + ".mp4"
    fourcc = cv2.VideoWriter_fourcc(*'XVID')

    out = cv2.VideoWriter(f"{output_path_noise}/{name_avi}", fourcc, fps, (W, H))

    if not out.isOpened():
        print("Erro ao criar vídeo:", name)
        continue
    
    while True:
        video_ = adicionar_ruido(frame, intensidade=20, por_canal=True)
        out.write(video_) 
        
        cv2.imshow("Video", video_)

        if cv2.waitKey(25) & 0xFF == ord('q'):
            break

        ret, frame = video.read()
        if not ret:
            break

    video.release()
    out.release()
    cv2.destroyAllWindows()

## rotation videos

for name in name_videos:
    
    video = cv2.VideoCapture(f"{input_path}/{name}")

    fps = video.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30

    ret, frame = video.read()
    if not ret:
        continue

    H, W = frame.shape[:2]

    # XVID -> AVI
    name_out = os.path.splitext(name)[0] + ".mp4"
    fourcc = cv2.VideoWriter_fourcc(*'XVID')

    out = cv2.VideoWriter(f"{output_path_rotation}/{name_out}", fourcc, fps, (W, H))

    if not out.isOpened():
        print("Erro ao criar vídeo:", name)
        continue

    while True:
        video_ = rotacionar_frame(frame, 10)
        out.write(video_) 
        
        cv2.imshow("Video", video_)

        if cv2.waitKey(25) & 0xFF == ord('q'):
            break

        ret, frame = video.read()
        if not ret:
            break

    video.release()
    out.release()
    cv2.destroyAllWindows()


