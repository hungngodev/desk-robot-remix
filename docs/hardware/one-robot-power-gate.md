# Protected single-cell power decision gate for one full robot

**The full robot battery and dock charger are not yet selected** because the assembled peak and continuous 5V currents have not been measured. The XIAO Sense official wiki documents a roughly **100 mA board battery charging path**, which is not a motor power system. Do not wire the steppers, MG90S or amplifier through the XIAO's onboard battery charge output. Reference https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/ .

The active 1S concept is: one correctly rated protected Li-ion cell/pack and fuse; a 5V boost regulator rated at **low pack voltage** for the *simultaneous* WROOM, Sense, two ULN2003/28BYJ48, two servos, audio amplifier and sensor loads (including any downstream 3.3V conversion); separately qualified charging and true load-sharing path; keyed and short-protected dock contacts; own stable sensor logic supply. This is not yet a PCB schematic, so do not place an unverified battery order.

New code/scripts/power_preflight.py accepts actual observed **peak and continuous 5V amperes**, worst-case cell voltage, measured boost efficiency and optional candidate current ratings. It prints a derated output and battery current requirement. If a product only advertises a max input rating, the script will not pretend that rating is its guaranteed output.

For example, an entirely hypothetical 3A peak at 5V, a 3.0V low cell and 85 percent efficiency requires >7.6A of protected cell and boost input rating after the 30 percent margin. Therefore Pololu's U3V50F5 **5A maximum input rating** is insufficient for that *example*, even though it is marketed as a 5V power regulator. It may be adequate for a lower verified load; its actual thermal output must be checked. Vendor https://www.pololu.com/product/2565/specs .

After actual measurement, example command:

    cd code
    uv run python scripts/power_preflight.py --peak-5v-a 3.0 --continuous-5v-a 1.8

The numbers above are **illustrative, not measurements of the user's robot**. The printed result never sets physical_load_verified or candidate_physically_qualified true. A charger with a power path and the protection/BMS are separate electrical design and physical verification tasks. Keep the charge contacts unpowered during software-only testing.

## Preserve the existing 1 W speaker without powering it from 5 V

The canonical `full-feature-plan.json` now keeps the original MAX98357A and 8 ohm, 1 W speaker but calls for a **rated, isolated 3.3 V supply to MAX98357A VDD** rather than the previously assumed 5 V supply. Analog Devices Rev 16 specifies operation at 2.5 to 5.5 V, and reports lower output at lower supply voltage; the amplifier is still bridge tied, so neither speaker terminal goes to GND. Use a correctly sized regulator drawn from the same protected system supply, not an unverified XIAO pin. This avoids the documented nominal 1.8 W, 8 ohm, 5 V mismatch on paper without changing the requested speaker. It is **not yet speaker thermal, distortion, acoustic output, supply headroom, or real carrier acceptance**. Engineer and measure that before purchasing or soldering the fleet. See [MAX98357A manufacturer datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/max98357a-max98357b.pdf).
