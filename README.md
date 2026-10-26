# VoiceFlow - AI Audio & Speech Toolkit

**VoiceFlow** é um kit de ferramentas local e poderoso para processamento de áudio, transcrição inteligente e síntese de voz baseada em Inteligência Artificial. Projetado com uma interface moderna e dark mode responsiva via [Eel](https://github.com/python-eel/Eel), o VoiceFlow integra modelos avançados como **Faster-Whisper** e **F5-TTS** para oferecer resultados profissionais de forma local.

![Interface do VoiceFlow](assets/screenshot.png)

---

## 🚀 Funcionalidades

### 1. Transcrição e Extração de Áudio
*   **Extração de Áudio**: Separe trilhas de áudio de arquivos de vídeo de forma automática usando FFmpeg.
*   **Transcrição Inteligente**: Transcreva áudio e vídeo usando o **Faster-Whisper** com suporte a aceleração por hardware (GPU/CUDA) ou CPU.
*   **Legendas no Estilo TikTok**: Gere legendas dinâmicas curtas e de leitura rápida, ideais para vídeos de formato curto (Reels, TikTok, Shorts). Customize:
    *   **Quantidade Máxima de Palavras**: Limite de palavras por linha (ex: 3 palavras).
    *   **Duração Máxima**: Limite de tempo por legenda (ex: 1.5 segundos).
*   **Formatos de Exportação**: Texto simples (`.txt`), legendas estruturadas (`.srt`) e WebVTT (`.vtt`).
*   **Visualização em Tempo Real**: Veja os blocos transcritos na tela conforme o áudio é processado.

### 2. Conversão de Texto em Fala (TTS)
*   **Vozes Neurais de Alta Qualidade**: Utiliza o motor do `edge-tts` para gerar falas extremamente naturais em português e dezenas de outros idiomas.
*   **Controle Dinâmico**: Ajuste a velocidade da fala (Speed) e o tom da voz (Pitch).
*   **Player Embutido**: Ouça o áudio gerado diretamente pela interface antes de exportar.

### 3. Clonagem de Voz (F5-TTS e OmniVoice)
*   **Dois motores selecionáveis**: **F5-TTS** (modelo original ou a versão em Português Brasileiro `firstpixel/F5-TTS-pt-br`) e **OmniVoice** ([k2-fsa](https://github.com/k2-fsa/OmniVoice), 600+ idiomas, instalação opcional).
*   **Melhor trecho da referência**: em vez de cortar os primeiros segundos, o app escolhe a janela de fala mais densa (cortando só no meio de pausas, nunca no meio de uma palavra) com a duração ideal de cada motor, e transcreve exatamente esse trecho.
*   **Verificação de qualidade**: avisa sobre referência curta, com pouca fala, muito ruído, volume baixo ou clipping.
*   **Auto-Transcrição**: Whisper transcreve o trecho de referência com um clique; se o trecho for recortado, o texto é atualizado automaticamente.
*   **Filtros Integrados**: remoção de ruído (aplicada só quando necessária), normalização de volume da referência e pós-processamento do resultado (corte de silêncio nas bordas, normalização de pico e fade).
*   **Textos longos (OmniVoice)**: divisão por frases (respeitando abreviações como "Dr." e decimais), mesma seed em todos os trechos e junção com crossfade de 50 ms.
*   **Controles F5-TTS**: passos NFE, seed, velocidade, fidelidade à voz (CFG) e Sway Sampling.

---

## 🛠️ Requisitos e Dependências

Para rodar o VoiceFlow localmente, você precisará de:

*   **Python 3.10+**
*   **FFmpeg** (gerenciado automaticamente pelo pacote `imageio-ffmpeg`)
*   **CUDA Toolkit (opcional, recomendado para GPU)**:
    *   Para aceleração na transcrição e clonagem de voz F5-TTS.

### Dependências principais (instaladas via `requirements.txt`):
*   `eel` (Frontend HTML/JS + Backend Python)
*   `faster-whisper` (Transcrição veloz)
*   `f5-tts` (Clonagem de voz via Flow Matching)
*   `edge-tts` (Síntese de voz da Microsoft)
*   `noisereduce` & `num2words` (Tratamento e pré-processamento de áudio)
*   `omnivoice` (**opcional**, segundo motor de clonagem): `pip install omnivoice`. Ele fixa suas próprias versões de `torch`/`transformers`; se houver conflito com o `f5-tts`, use outro ambiente virtual.

---

## 📦 Instalação e Execução

1. **Clone o repositório**:
   ```bash
   git clone https://github.com/seu-usuario/tiktok-dark-tools.git
   cd tiktok-dark-tools
   ```

2. **Crie e ative um ambiente virtual**:
   ```bash
   python -m venv venv
   # No Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   # No Linux/macOS:
   source venv/bin/activate
   ```

3. **Instale as dependências**:
   ```bash
   pip install -r requirements.txt
   ```

4. **(Opcional) Instale o OmniVoice** para usá-lo como motor de clonagem:
   ```bash
   pip install omnivoice
   ```

5. **Inicie o aplicativo**:
   ```bash
   python main.py
   ```

6. **Rode os testes** dos utilitários de áudio/texto (não precisam de GPU nem de modelos):
   ```bash
   pip install pytest
   python -m pytest tests
   ```

### Dicas para uma boa clonagem
*   Use de **5 a 12 segundos** de fala limpa, de um só falante, sem música ao fundo. Referências longas pioram o resultado (o app seleciona o melhor trecho automaticamente).
*   Confira o texto da transcrição de referência: erros nele geram palavras engolidas ou repetidas no início do áudio.
*   Se gostou de um resultado, anote a **seed** exibida ao final para reproduzi-lo.

---

## 🖥️ Configuração do CUDA (Aceleração por GPU no Windows)

O VoiceFlow já vem pré-configurado para localizar bibliotecas NVIDIA CUDA instaladas no próprio ambiente Python. Se você deseja transcrever e clonar vozes de forma instantânea usando sua GPU GeForce:

1. Certifique-se de que sua placa é compatível com CUDA e que os drivers da NVIDIA estão atualizados.
2. Ao selecionar o dispositivo **GPU (CUDA)** na interface do programa, ele utilizará as bibliotecas CUDA pré-carregadas instaladas via pip (`nvidia-cublas-cu12`, etc).

---

## 📝 Licença

Este projeto é distribuído sob a licença MIT. Consulte o arquivo `LICENSE` para obter mais informações.
