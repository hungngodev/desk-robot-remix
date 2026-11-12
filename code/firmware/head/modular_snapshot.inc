std::expected<std::vector<uint8_t>, std::string> Esp32Camera::SnapshotJpeg() {
    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());
    // Capture joins any previous encoder and discards queued frames before
    // obtaining a new frame. Never serve the last Explain frame as a snapshot.
    if (!Capture() || !current_fb_ || !current_fb_->buf || !current_fb_->len)
        return std::unexpected("Fresh camera capture failed");
    if (current_fb_->format == PIXFORMAT_JPEG) {
        // Native sensor JPEG is already compressed. Copy its bounded bytes
        // while Capture owns the frame buffer; never run an RGB565 encoder
        // on the microphone-sensitive Sense path. Reject truncated JPEGs.
        const size_t len = current_fb_->len;
        const uint8_t* buf = current_fb_->buf;
        if (len < 4 || len > 512 * 1024 ||
            buf[0] != 0xff || buf[1] != 0xd8 ||
            buf[len - 2] != 0xff || buf[len - 1] != 0xd9)
            return std::unexpected("Invalid camera JPEG frame");
        return std::vector<uint8_t>(buf, buf + len);
    }
    // The board uses RGB565. Capture prepares the same byte-swapped buffer
    // used by the upstream Explain encoder, preserving camera color handling.
    if (current_fb_->format != PIXFORMAT_RGB565 || !encode_buf_)
        return std::unexpected("Unsupported snapshot pixel format");
    uint8_t* jpeg = nullptr;
    size_t len = 0;
    const bool ok = image_to_jpeg(encode_buf_, current_fb_->width * current_fb_->height * 2,
        current_fb_->width, current_fb_->height, V4L2_PIX_FMT_RGB565, 80, &jpeg, &len);
    if (!ok || !jpeg || len < 4 || len > 512 * 1024) {
        free(jpeg);
        return std::unexpected("JPEG encoding failed");
    }
    std::vector<uint8_t> result(jpeg, jpeg + len);
    free(jpeg);
    return result;
}
