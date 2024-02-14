#!/bin/bash
for device in $(ls /dev/video*); do
    if v4l2-ctl --device=${device} -D --list-formats | grep -q MJPG; then
        echo '>>>>' ${device} '<<<<'
        v4l2-ctl --device=${device} -D --list-formats

        #vlc v4l2://${device} --v4l2-width 1920 --v4l2-height 1080 --v4l2-chroma MJPG --vout-filter=transform --transform-type=180  &>/dev/null &
        vlc v4l2://${device} --v4l2-width 1920 --v4l2-height 1080 --v4l2-chroma MJPG &>/dev/null &
        echo ==========================================
    fi
done
wait

# ffmpeg -f v4l2 -framerate 25 -video_size 1920x1080 -input_format mjpeg -i /dev/video1 -f mpegts udp://127.0.0.1:6001 &
# ffmpeg -f v4l2 -framerate 25 -video_size 1920x1080 -input_format mjpeg -i /dev/video2 -f mpegts udp://127.0.0.1:6002 &
# ffmpeg -f v4l2 -framerate 25 -video_size 1920x1080 -input_format mjpeg -i /dev/video4 -f mpegts udp://127.0.0.1:6003 &
# vlc udp://@:6001 &
# vlc udp://@:6002 &
# vlc udp://@:6003 

