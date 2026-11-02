//! Python's `random.Random`, bit for bit: the MT19937 generator seeded from an integer by `init_by_array` over the
//! integer's 32-bit words, `random()`'s 53-bit doubles, and `gauss`'s Box-Muller pair. The Python's seeded sensor noise
//! (the drum-fill current) draws from it, so a port that must agree draw for draw uses this.

const N: usize = 624;
const M: usize = 397;

/// Python's `random.Random(seed)`.
#[derive(Debug, Clone)]
pub struct Mt19937 {
    mt: [u32; N],
    i: usize,
    gauss_next: Option<f64>,
}

impl Mt19937 {
    fn init_genrand(s: u32) -> Self {
        let mut mt = [0_u32; N];
        mt[0] = s;
        for i in 1..N {
            #[allow(clippy::cast_possible_truncation)] // i < 624
            let k = i as u32;
            mt[i] = 1_812_433_253_u32
                .wrapping_mul(mt[i - 1] ^ (mt[i - 1] >> 30))
                .wrapping_add(k);
        }
        Self {
            mt,
            i: N,
            gauss_next: None,
        }
    }

    /// `random.Random(seed)` for a non-negative integer seed: `init_by_array` over its 32-bit words, least
    /// significant first (`[0]` for zero).
    #[must_use]
    pub fn new(seed: u128) -> Self {
        let mut key = Vec::new();
        let mut n = seed;
        loop {
            #[allow(clippy::cast_possible_truncation)] // the low 32 bits, by construction
            key.push((n & 0xffff_ffff) as u32);
            n >>= 32;
            if n == 0 {
                break;
            }
        }
        let mut g = Self::init_genrand(19_650_218);
        let (mut i, mut j) = (1_usize, 0_usize);
        for _ in 0..N.max(key.len()) {
            let prev = g.mt[i - 1] ^ (g.mt[i - 1] >> 30);
            #[allow(clippy::cast_possible_truncation)] // j < key length
            let jj = j as u32;
            g.mt[i] = (g.mt[i] ^ prev.wrapping_mul(1_664_525))
                .wrapping_add(key[j])
                .wrapping_add(jj);
            i += 1;
            j += 1;
            if i >= N {
                g.mt[0] = g.mt[N - 1];
                i = 1;
            }
            if j >= key.len() {
                j = 0;
            }
        }
        for _ in 0..N - 1 {
            let prev = g.mt[i - 1] ^ (g.mt[i - 1] >> 30);
            #[allow(clippy::cast_possible_truncation)] // i < 624
            let ii = i as u32;
            g.mt[i] = (g.mt[i] ^ prev.wrapping_mul(1_566_083_941)).wrapping_sub(ii);
            i += 1;
            if i >= N {
                g.mt[0] = g.mt[N - 1];
                i = 1;
            }
        }
        g.mt[0] = 0x8000_0000;
        g
    }

    /// The next 32-bit output (`getrandbits(32)`).
    pub fn next_u32(&mut self) -> u32 {
        if self.i >= N {
            for k in 0..N {
                let y = (self.mt[k] & 0x8000_0000) | (self.mt[(k + 1) % N] & 0x7fff_ffff);
                let mag = if y & 1 == 0 { 0 } else { 0x9908_b0df };
                self.mt[k] = self.mt[(k + M) % N] ^ (y >> 1) ^ mag;
            }
            self.i = 0;
        }
        let mut y = self.mt[self.i];
        self.i += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^ (y >> 18)
    }

    /// `random()`: a double in [0, 1) from two outputs' top 27 and 26 bits.
    pub fn random(&mut self) -> f64 {
        let a = f64::from(self.next_u32() >> 5);
        let b = f64::from(self.next_u32() >> 6);
        (a * 67_108_864.0 + b) * (1.0 / 9_007_199_254_740_992.0)
    }

    /// `gauss(mu, sigma)`: Box-Muller, the pair's second value kept for the next call.
    pub fn gauss(&mut self, mu: f64, sigma: f64) -> f64 {
        let z = if let Some(z) = self.gauss_next.take() {
            z
        } else {
            let x2pi = self.random() * std::f64::consts::TAU;
            let g2rad = (-2.0 * (1.0 - self.random()).ln()).sqrt();
            self.gauss_next = Some(x2pi.sin() * g2rad);
            x2pi.cos() * g2rad
        };
        mu + z * sigma
    }
}

#[cfg(test)]
mod tests {
    use super::Mt19937;

    #[test]
    #[allow(clippy::float_cmp)] // the draws are bit-exact
    fn draws_match_pythons_random() {
        // expected values from CPython's `random.Random(seed)`: getrandbits(32) x3, random() x2, gauss(0, 1)
        for (seed, bits, floats, gauss) in [
            (
                0_u128,
                [3_626_764_237_u32, 1_654_615_998, 3_255_389_356],
                [0.844_421_851_525_048_1, 0.757_954_402_940_302_5],
                0.941_715_404_680_664_4,
            ),
            (
                7,
                [1_390_851_128, 4_071_050_724, 647_892_279],
                [0.323_832_764_833_162_37, 0.150_849_173_924_501_92],
                -0.255_880_288_447_600_4,
            ),
            (
                (1 << 40) + 3,
                [943_978_446, 261_273_136, 2_359_950_418],
                [0.219_787_106_371_167_16, 0.549_468_776_835_220_3],
                0.238_283_575_124_940_3,
            ),
        ] {
            let mut g = Mt19937::new(seed);
            assert_eq!(
                [g.next_u32(), g.next_u32(), g.next_u32()],
                bits,
                "seed {seed}"
            );
            let mut g = Mt19937::new(seed);
            assert_eq!([g.random(), g.random()], floats, "seed {seed}");
            let mut g = Mt19937::new(seed);
            let z = g.gauss(0.0, 1.0);
            assert!((z - gauss).abs() <= 1e-15, "seed {seed}: {z} vs {gauss}");
        }
    }
}
