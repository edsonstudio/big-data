import time
import requests
import random
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
from pydub import AudioSegment
import subprocess
import os

# --- CONFIGURAÇÕES DA MATRIX (mantidas) ---
options = RGBMatrixOptions()
options.rows = 32
options.cols = 64
options.chain_length = 3
options.parallel = 1
options.hardware_mapping = 'adafruit-hat'
options.gpio_slowdown = 4
options.brightness = 100
options.drop_privileges = False
matrix = RGBMatrix(options=options)

# --- Configurações da API ---
API_URL_BASE = "http://192.168.0.138:9432"
TERMOS_DE_BUSCA = [
    # Mercearia
    "arroz", "feijão", "açúcar", "sal", "farinha de trigo",
    "macarrão", "óleo de soja", "azeite", "café", "leite integral",
    # Bebidas
    "refrigerante coca cola", "suco de laranja", "cerveja",
    "água mineral", "refrigerante guaraná",
    # Higiene
    "sabonete", "shampoo", "desodorante", "pasta de dente", "papel higiênico",
    # Limpeza
    "detergente", "sabão em pó", "água sanitária", "desinfetante",
    # Frios/Laticínios
    "queijo mussarela", "presunto", "iogurte", "manteiga",
    # Padaria
    "pão de forma", "biscoito", "torrada",
    # Carnes
    "frango", "carne bovina", "linguiça", "ovo",
]

# --- Variáveis Globais ---
offscreen_canvas = matrix.CreateFrameCanvas()
font_pequena = graphics.Font()
font_pequena.LoadFont("/home/edsonstudio/rpi-rgb-led-matrix/fonts/7x13.bdf")
font_grande = graphics.Font()
font_grande.LoadFont("/home/edsonstudio/rpi-rgb-led-matrix/fonts/9x18B.bdf")

# --- Estados ---
last_promotion_check_time = 0
promotion_check_interval = 60
current_promotions = []
promotion_index = 0
is_showing_promotion = False
time_on_promotion = 0
promotion_display_duration = 15

# --- Função TTS ---
def speak_text(text):
    try:
        audio_filename = "/tmp/tts_audio.wav"

        # 1. Gerar o áudio com espeak (roda como root, pois o script é sudo)
        subprocess.run(["espeak", "-v", "pt+f3", "-s", "150", "-w", audio_filename, text], check=True)

        # 2. IMPORTANTE: Dar permissão de leitura para todos no arquivo gerado
        # Como o espeak rodou como root, o arquivo pertence ao root.
        # O usuário 'edsonstudio' precisa ler para tocar.
        subprocess.run(["chmod", "644", audio_filename], check=True)

        # 3. Descobrir o ID do usuário edsonstudio para montar o caminho do socket
        try:
            user_id_str = subprocess.check_output(['id', '-u', 'edsonstudio']).decode('utf-8').strip()
            xdg_runtime = f"/run/user/{user_id_str}"
        except:
            # Fallback se falhar a detecção automática
            xdg_runtime = "/run/user/1000"

        # 4. Montar o comando para tocar como 'edsonstudio'
        # Uso 'env' para garantir que a variável XDG_RUNTIME_DIR exista para o aplay
        cmd_play = [
            "sudo", 
            "-u", "edsonstudio", 
            "env", f"XDG_RUNTIME_DIR={xdg_runtime}", 
            "aplay", 
            "-D", "default", # Força o dispositivo default (PulseAudio/Bluetooth)
            audio_filename
        ]

        # Executa a reprodução
        subprocess.run(cmd_play, check=True)

        print(f"DEBUG: TTS falou: '{text}'")

    except subprocess.CalledProcessError as e:
        print(f"ERRO TTS (Comando falhou): {e}")
    except Exception as e:
        print(f"ERRO TTS (Geral): {e}")


# --- Blink do preço ---
def draw_blinking_price(canvas, font, x, y, price_text, blink_color, off_color, blink_interval=0.5):
    if int(time.time() / blink_interval) % 2 == 0:
        graphics.DrawText(canvas, font, x, y, blink_color, price_text)
    else:
        graphics.DrawText(canvas, font, x, y, off_color, price_text)


# --- Exibir no LED ---
def exibir_preco_no_led(nome_produto, preco_produto, marca_produto, termo_busca, is_promotion_flag=False, desconto_pct=None):
    global offscreen_canvas, matrix, font_pequena, font_grande

    def get_truncated_text_and_width(text, font, max_width_pixels):
        original_text = text
        current_text = text
        text_width = graphics.DrawText(offscreen_canvas, font, 0, 0, graphics.Color(0, 0, 0), current_text)

        while text_width > max_width_pixels and len(current_text) > 3:
            current_text = current_text[:-1]
            text_width = graphics.DrawText(offscreen_canvas, font, 0, 0, graphics.Color(0, 0, 0), current_text)

        if len(original_text) > len(current_text):
            final_text = current_text[:-3] + '...' if len(current_text) >= 3 else current_text
        else:
            final_text = current_text

        final_width = graphics.DrawText(offscreen_canvas, font, 0, 0, graphics.Color(0, 0, 0), final_text)
        return final_text, final_width

    max_pixel_width = matrix.width - 2

    oferta_text_display, _ = get_truncated_text_and_width(nome_produto, font_pequena, max_pixel_width)
    marca_text_display, _ = get_truncated_text_and_width(marca_produto, font_pequena, max_pixel_width)

    preco_raw_text = f"R$ {preco_produto:.2f}"
    preco_text_display, _ = get_truncated_text_and_width(preco_raw_text, font_grande, max_pixel_width)

    offscreen_canvas.Clear()

    # Cores
    cor_nome = graphics.Color(255, 105, 180)
    cor_preco_normal = graphics.Color(0, 0, 255)
    cor_marca = graphics.Color(150, 150, 150)
    cor_nome_promo = graphics.Color(255, 255, 0)
    cor_preco_promo = graphics.Color(255, 0, 0)
    cor_off = graphics.Color(0, 0, 0)

    y_nome = 1 + font_pequena.baseline
    graphics.DrawText(
        offscreen_canvas,
        font_pequena,
        1,
        y_nome,
        cor_nome_promo if is_promotion_flag else cor_nome,
        oferta_text_display
    )

    y_preco = y_nome - font_pequena.baseline + font_pequena.height + font_grande.baseline

    if is_promotion_flag:
        draw_blinking_price(offscreen_canvas, font_grande, 1, y_preco, preco_text_display, cor_preco_promo, cor_off)
    else:
        graphics.DrawText(offscreen_canvas, font_grande, 1, y_preco, cor_preco_normal, preco_text_display)

    y_marca = y_preco - font_grande.baseline + font_grande.height + font_pequena.baseline

    if is_promotion_flag and desconto_pct:
        desconto_text = f"-{desconto_pct}% OFF!"
        cor_desconto = graphics.Color(0, 255, 0)
        graphics.DrawText(offscreen_canvas, font_pequena, 1, y_marca, cor_desconto, desconto_text)
    elif marca_text_display and not is_promotion_flag:
        graphics.DrawText(offscreen_canvas, font_pequena, 1, y_marca, cor_marca, marca_text_display)

    offscreen_canvas = matrix.SwapOnVSync(offscreen_canvas)


# --- Loop principal ---
def run_display():
    global offscreen_canvas, last_promotion_check_time, current_promotions
    global promotion_index, is_showing_promotion, time_on_promotion

    speak_text("Bem-vindo ao sistema de anúncios de promoções!")

    while True:
        current_time = time.time()

        # --- Exibindo promoções ---
        if is_showing_promotion:
            if current_promotions and promotion_index < len(current_promotions):
                promo = current_promotions[promotion_index]

                exibir_preco_no_led(
                    promo['nome'], promo['preco'], promo['marca'],
                    promo['termo_busca'], is_promotion_flag=True,
                    desconto_pct=promo.get('desconto_percentual')
                )

                time.sleep(0.1)
                time_on_promotion += 0.1

                if time_on_promotion >= promotion_display_duration:
                    time_on_promotion = 0
                    promotion_index = (promotion_index + 1) % len(current_promotions)

                    if promotion_index == 0:
                        is_showing_promotion = False
            else:
                is_showing_promotion = False

        # --- Produtos normais ---
        else:
            if current_time - last_promotion_check_time >= promotion_check_interval:
                print("Verificando novas promoções...")

                try:
                    promo_resp = requests.get(f"{API_URL_BASE}/promocoes")
                    promo_resp.raise_for_status()
                    promo_data = promo_resp.json()

                    if promo_data.get("status") == "sucesso" and promo_data.get("promocoes"):
                        new_promotions = promo_data["promocoes"]

                        if len(new_promotions) > len(current_promotions) or any(p not in current_promotions for p in new_promotions):
                            current_promotions = new_promotions
                            promotion_index = 0

                            print(f"DEBUG: {len(current_promotions)} novas promoções!")

                            first_promo = current_promotions[0]
                            tts_message = f"Temos uma nova promoção para {first_promo['nome']} por {first_promo['preco']:.2f} reais."
                            speak_text(tts_message)

                            is_showing_promotion = True
                        else:
                            current_promotions = new_promotions

                    else:
                        current_promotions = []
                        print("Nenhuma promoção ativa.")
                except Exception as e:
                    print(f"ERRO API Promoções: {e}")

                last_promotion_check_time = current_time

            if not is_showing_promotion:
                termo = random.choice(TERMOS_DE_BUSCA)

                try:
                    resp = requests.get(f"{API_URL_BASE}/precos/{termo}")
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("status") == "sucesso":
                        exibir_preco_no_led(
                            data["nome"], data["preco"], data["marca"],
                            termo, is_promotion_flag=False
                        )
                        print(f"Exibindo: {data['nome']} - R$ {data['preco']:.2f}")

                except Exception as e:
                    print(f"ERRO API Preços: {e}")

            time.sleep(1)


# --- MAIN ---
if __name__ == '__main__':
    try:
        run_display()
    except KeyboardInterrupt:
        print("\nEncerrando o display de LED.")
        offscreen_canvas.Clear()
        matrix.SwapOnVSync(offscreen_canvas)
