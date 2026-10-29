std::expected<std::vector<uint8_t>, std::string> Esp32Camera::SnapshotJpeg() {
    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());
    // Capture joins any previous encoder and discards queued frames before
    // obtaining a new frame. Never serve the last Explain frame as a snapshot.
    if (!Capture() || !current_fb_ || !current_fb_->buf || !current_fb_->len)
        return std::unexpected("Fresh camera capture failed");
    if (current_fb_->format == PIXFORMAT_JPEG) {
        if (current_fb_->len < 4 || current_fb_->len > 512 * 1024)
            return std::unexpected("Invalid camera JPEG size");
        return std::vector<uint8_t>(current_fb_->buf, current_fb_->buf + current_fb_->len);
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
