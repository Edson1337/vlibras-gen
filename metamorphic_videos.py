import cv2
import os
import numpy as np


def mudar_iluminacao(frame, fator=1.5):  
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * fator, 0, 255).astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

def adicionar_ruido(frame, intensidade=25):
    ruido = np.random.normal(0, intensidade, frame.shape).astype(np.int16)
    frame_ruidoso = np.clip(frame.astype(np.int16) + ruido, 0, 255).astype(np.uint8)
    return frame_ruidoso

def rotacionar_frame(frame, angulo=5):
    altura, largura = frame.shape[:2]
    centro = (largura // 2, altura // 2)
    
    matriz = cv2.getRotationMatrix2D(centro, angulo, 1.0)
    rotacionado = cv2.warpAffine(frame, matriz, (largura, altura))
    
    return rotacionado

def frame_dropping(frame, probabilidade=0.1):
    if np.random.rand() < probabilidade:
        return None
    return frame

def acelerar_video(frame, frame_atual, fator=2):
    if frame_atual % int(fator) != 0:
        return None
    return frame


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
        video_ = mudar_iluminacao(frame, 3)
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

    fator = 2

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
        video_ = frame_dropping(frame, 0.5)

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
        video_ = adicionar_ruido(frame, intensidade=30)
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


