# Đọc Giùm — TTS Tiếng Việt (Nam Minh & Hoài My)

Web tự host trên điện thoại qua Termux, dùng engine **edge-tts** (miễn phí,
không cần API key, không cần thẻ tín dụng). Hỗ trợ văn bản tới 20.000 ký
tự/lần, tự chia nhỏ + xử lý song song + ghép audio.

## Vì sao không cần API key Azure?
`vi-VN-NamMinhNeural` và `vi-VN-HoaiMyNeural` là 2 giọng neural của Microsoft
Edge. Thư viện `edge-tts` gọi thẳng dịch vụ đọc-to-trang-web miễn phí này mà
không cần đăng ký hay API key.

## Cài đặt (Termux, Android)
pkg update -y && pkg upgrade -y
pkg install python ffmpeg git -y
pkg install python-pip -y
pip install flask edge-tts pydub audioop-lts
git clone https://github.com/khnggmr-del/TTS-VIETNAMESE-by-Khanz094.git
cd TTS-VIETNAMESE-by-Khanz094
##Chạy
termux-wake-lock
python app.py
Mở Chrome, gõ `127.0.0.1:8000`.

## Tính năng
- 2 giọng: Nam Minh (nam), Hoài My (nữ)
- Tối đa 20.000 ký tự/lần, tự chia đoạn (2000 ký tự/đoạn), xử lý song song
  3 đoạn cùng lúc để nhanh hơn
- Thanh tiến trình theo thời gian thực
- Đặt tên file MP3 tuỳ ý
- Lưu lịch sử các lần tạo (tối đa 50 lần gần nhất), nghe lại/tải/xoá được
- Tự thử lại tối đa 3 lần nếu mất kết nối tạm thời tới dịch vụ giọng đọc

## Vì sao chạy trên điện thoại (Termux) chứ không phải server cloud?
Microsoft chặn IP từ các server cloud phổ biến (Render, Hugging Face,
Railway...) gọi tới dịch vụ Edge TTS miễn phí này. IP nhà/di động (residential)
không bị chặn, nên giải pháp ổn định nhất với chi phí 0đ là tự host ngay trên
điện thoại.

## Cấu trúc project
app.py              — backend Flask + edge-tts
static/index.html   — giao diện web
requirements.txt    — thư viện Python cần cài
history/             — audio đã tạo (tự sinh ra khi chạy, không commit lên git)
