# HIL-Testbench

This is a hardware-in-the-loop test setup for an STM32 Nucleo-F446RE. A Python script on my laptop sends commands over UART to firmware running on the board, and I measure how long it takes to respond. I time it two ways: once on the microcontroller itself (using its cycle counter, so it's accurate to nanoseconds) and once from the host side (regular wall-clock time). Then I run it a bunch of times and look at the actual stats instead of just eyeballing one result.

I built this because I wanted to actually measure timing behavior on a microcontroller instead of just assuming firmware works because it compiles and doesn't crash.

## Hardware setup

- Board: STM32 Nucleo-F446RE
- No extra wiring needed. The Nucleo's onboard ST-Link already connects to USART2 through USB, so it just shows up as a normal COM port (or `/dev/ttyACM0` on Linux) when you plug it in.
- UART settings: 115200 baud, 8 data bits, no parity, 1 stop bit

## How the protocol works

The firmware just reads a line of text ending in a newline and sends one line back:

| You send | It replies | What happens |
|---|---|---|
| `PING` | `OK` | just checks the board is alive |
| `RESET` | `OK` | resets the cycle counter to 0 |
| `TOGGLE` | `LATENCY_NS <n> CYCLES <c>` | flips the onboard LED and tells you how many cycles/ns that took |
| anything else | `ERR` | didn't recognize the command |

I used the DWT cycle counter for the timing instead of `HAL_GetTick()`. `HAL_GetTick()` only updates every 1ms, and the actual toggle takes way less than a millisecond, so it would've just read 0 every time and told me nothing.

## How to run it

1. Open the project in STM32CubeIDE and flash it to the board (hit Run, it builds and flashes automatically over the ST-Link).
2. Install pyserial: `pip install pyserial`
3. Run the test script:
   ```
   python run_tests.py --port COMx --iters 1000 --delta-iters 100
   ```
   - `--iters` = how many times to run the TOGGLE latency test (default 1000)
   - `--delta-iters` = how many PING/TOGGLE pairs to run for the byte-cost comparison (default 100)
   - `--pass-max-ns` = optional pass/fail threshold. Don't set this until you've actually run the test once and seen real numbers — don't just guess a number

It writes everything to `Reports/`: `latency.csv` (every single trial), `ping_toggle_delta.csv`, and `summary.txt` with the averages.

## What I actually found

All numbers below are from my `Reports/` folder, 1000 trials for the main latency test and 100 for the PING/TOGGLE comparison.

**On-chip latency (how long the actual GPIO toggle takes):**
- With interrupts turned off during the measurement: **642ns**, exactly the same every single time across 1000 trials, and I also ran it for 10,000 trials just to be sure and got the same flat result.
- With interrupts left on: **654ns** most of the time, but out of 10,000 trials, 6 of them (0.06%) came back higher, up to about 1392ns. When I looked closer, those weird readings were all spaced almost exactly one CPU cycle apart from each other, which lines up with what happens when an interrupt (SysTick, which fires every 1ms) happens to fire in the middle of my measurement window. So it's not random noise, it's the SysTick interrupt occasionally getting in the way. That's why I disable interrupts for that tiny window in the final version, it makes the number 100% consistent instead of "almost always the same."

**Round-trip latency (how long it takes from my laptop sending a command to getting the reply):**
- min=3078.9us, max=4879.1us, mean=3816.0us. So a few milliseconds, compared to the 642ns for the actual on-chip work, meaning most of the delay is just getting the bytes over UART, not the MCU being slow.
- I checked this by comparing PING (short reply) against TOGGLE (longer reply) directly. At 115200 baud, each byte takes about 86.8 microseconds to send, and the TOGGLE reply is about 22 bytes longer than PING's, so I predicted about a 2ms difference between the two. When I actually measured it (100 trials), I got a 2671.8us average difference with a 439.1us standard deviation, which lines up with what I predicted, so that pretty much confirms the delay is coming from UART transmit time and not something else like USB polling.

**Threshold:** I'd set `--pass-max-ns` somewhere around 700-800ns, which gives some margin above the 642ns worst case I actually measured. The point is picking a number based on real data instead of just guessing, which is what I did the first time around (see below).

## Bugs I ran into (and fixed)

Wanted to leave this in instead of pretending it worked perfectly the first time:

- My test script originally sent `GARBAGE` as a startup check instead of `PING`, so it crashed immediately every time I ran it.
- The pass/fail check was broken — it stored the max latency value instead of actually comparing it to the threshold, so it always printed "PASS" no matter what, because in Python any nonzero number counts as true.
- Before I had real UART code working, I was testing against a fake Python function that just returned random numbers instead of actually talking to the board. So technically none of my early "results" were real hardware data.
- At one point I disabled interrupts for the timing measurement but forgot to turn them back on, which quietly broke the board's internal millisecond timer after the first TOGGLE call. Didn't catch it right away because it didn't cause a crash, it just would've caused problems if the code had relied on that timer later.

## What I'd add if I kept working on this

- Test at different baud rates to see if the round-trip delay actually scales the way the math predicts
- Try an interrupt-driven UART receive instead of polling, and compare the timing
- Add more commands than just toggling one LED, to see how latency changes with more complex operations
