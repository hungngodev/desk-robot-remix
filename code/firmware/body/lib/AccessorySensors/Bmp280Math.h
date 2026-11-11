#pragma once
// BMP280 factory compensation from Bosch Sensortec datasheet BST-BMP280-DS001.
// Original independently written adapter around the documented register math.
// This is an ambient read-only sensor, never a cliff, battery or motion gate.
#include <cmath>
#include <cstdint>
namespace desk_robot {
struct Bmp280Trim {
  std::uint16_t t1 = 0, p1 = 0;
  std::int16_t t2 = 0, t3 = 0;
  std::int16_t p2 = 0, p3 = 0, p4 = 0, p5 = 0;
  std::int16_t p6 = 0, p7 = 0, p8 = 0, p9 = 0;
};
inline std::uint16_t bmp_u16(const std::uint8_t* v) {
  return static_cast<std::uint16_t>(v[0] | (static_cast<unsigned>(v[1]) << 8));
}
inline std::int16_t bmp_s16(const std::uint8_t* v) {
  return static_cast<std::int16_t>(bmp_u16(v));
}
inline bool bmp280_trim(const std::uint8_t* b, Bmp280Trim& out) {
  if (!b) return false;
  out.t1 = bmp_u16(b);
  out.t2 = bmp_s16(b + 2);
  out.t3 = bmp_s16(b + 4);
  out.p1 = bmp_u16(b + 6);
  out.p2 = bmp_s16(b + 8);
  out.p3 = bmp_s16(b + 10);
  out.p4 = bmp_s16(b + 12);
  out.p5 = bmp_s16(b + 14);
  out.p6 = bmp_s16(b + 16);
  out.p7 = bmp_s16(b + 18);
  out.p8 = bmp_s16(b + 20);
  out.p9 = bmp_s16(b + 22);
  return out.t1 != 0 && out.p1 != 0;
}
inline bool bmp280_compensate(const Bmp280Trim& d, std::uint32_t raw_t,
                             std::uint32_t raw_p, int& temp_centi,
                             unsigned& pressure_pa) {
  if (!d.t1 || !d.p1 || raw_t == 0x80000U || raw_p == 0x80000U ||
      raw_t > 0xfffffU || raw_p > 0xfffffU) return false;
  const double v1 = (static_cast<double>(raw_t) / 16384.0 -
                     d.t1 / 1024.0) * d.t2;
  const double term = static_cast<double>(raw_t) / 131072.0 - d.t1 / 8192.0;
  const double v2 = term * term * d.t3;
  const double fine = v1 + v2;
  const double celsius = fine / 5120.0;
  double a = fine / 2.0 - 64000.0;
  double b = a * a * d.p6 / 32768.0;
  b = b + a * d.p5 * 2.0;
  b = b / 4.0 + d.p4 * 65536.0;
  a = (d.p3 * a * a / 524288.0 + d.p2 * a) / 524288.0;
  a = (1.0 + a / 32768.0) * d.p1;
  if (!std::isfinite(a) || std::fabs(a) < 1e-6) return false;
  double p = 1048576.0 - raw_p;
  p = (p - b / 4096.0) * 6250.0 / a;
  a = d.p9 * p * p / 2147483648.0;
  b = p * d.p8 / 32768.0;
  p += (a + b + d.p7) / 16.0;
  // Atmospheric range is intentionally broad. Do not report corrupt trim as
  // a sensor event or infer weather, altitude or a health measurement.
  if (!std::isfinite(p) || !std::isfinite(celsius) ||
      p < 30000 || p > 120000 || celsius < -40 || celsius > 85)
    return false;
  temp_centi = static_cast<int>(std::round(celsius * 100));
  pressure_pa = static_cast<unsigned>(std::round(p));
  return true;
}
inline std::uint32_t bmp280_raw20(const std::uint8_t* b) {
  return (static_cast<std::uint32_t>(b[0]) << 12) |
         (static_cast<std::uint32_t>(b[1]) << 4) | (b[2] >> 4);
}
}  // namespace desk_robot
