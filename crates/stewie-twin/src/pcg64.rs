//! numpy's default generator, bit for bit (`numpy.random.default_rng(seed)`): the `SeedSequence` entropy pool
//! hashed from an integer seed, the PCG64 (XSL-RR 128/64) state it seeds, and `Generator.random()`'s 53-bit
//! doubles. The Python's seeded simulations (the telemetry link's packet drops) draw from it, so a port that
//! must agree draw for draw uses this.

const INIT_A: u32 = 0x43b0_d7e5;
const MULT_A: u32 = 0x931e_8875;
const INIT_B: u32 = 0x8b51_f9dd;
const MULT_B: u32 = 0x58f3_8ded;
const MIX_MULT_L: u32 = 0xca01_f9dd;
const MIX_MULT_R: u32 = 0x4973_f715;
const XSHIFT: u32 = 16;
const POOL: usize = 4;
const PCG_MULT: u128 = 0x2360_ed05_1fc6_5da4_4385_df64_9fcc_f645;

fn hashmix(value: u32, hash: &mut u32) -> u32 {
    let mut v = value ^ *hash;
    *hash = hash.wrapping_mul(MULT_A);
    v = v.wrapping_mul(*hash);
    v ^ (v >> XSHIFT)
}

fn mix(x: u32, y: u32) -> u32 {
    let r = MIX_MULT_L
        .wrapping_mul(x)
        .wrapping_sub(MIX_MULT_R.wrapping_mul(y));
    r ^ (r >> XSHIFT)
}

/// `SeedSequence(seed).generate_state(4, uint64)`: the integer's 32-bit words (least significant first; `[0]`
/// for zero) mixed into a four-word pool, then hashed out as eight words combined little-endian.
fn seed_sequence_state(seed: u128) -> [u64; 4] {
    let mut entropy = Vec::new();
    let mut n = seed;
    loop {
        #[allow(clippy::cast_possible_truncation)] // the low 32 bits, by construction
        entropy.push((n & 0xffff_ffff) as u32);
        n >>= 32;
        if n == 0 {
            break;
        }
    }
    let mut hash = INIT_A;
    let mut pool = [0_u32; POOL];
    for (i, slot) in pool.iter_mut().enumerate() {
        *slot = hashmix(entropy.get(i).copied().unwrap_or(0), &mut hash);
    }
    for src in 0..POOL {
        for dst in 0..POOL {
            if src != dst {
                let h = hashmix(pool[src], &mut hash);
                pool[dst] = mix(pool[dst], h);
            }
        }
    }
    for &e in entropy.iter().skip(POOL) {
        for slot in &mut pool {
            let h = hashmix(e, &mut hash);
            *slot = mix(*slot, h);
        }
    }
    let mut hash = INIT_B;
    let mut words = [0_u32; 2 * POOL];
    for (i, w) in words.iter_mut().enumerate() {
        let mut v = pool[i % POOL] ^ hash;
        hash = hash.wrapping_mul(MULT_B);
        v = v.wrapping_mul(hash);
        *w = v ^ (v >> XSHIFT);
    }
    std::array::from_fn(|k| u64::from(words[2 * k]) | (u64::from(words[2 * k + 1]) << 32))
}

/// numpy's PCG64 bit generator.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pcg64 {
    state: u128,
    inc: u128,
    /// numpy's `has_uint32` / `uinteger`: the upper half of a 64-bit output kept for the next 32-bit draw.
    spare_u32: Option<u32>,
}

impl Pcg64 {
    /// `numpy.random.default_rng(seed)`'s generator for a non-negative integer seed.
    #[must_use]
    pub fn new(seed: u128) -> Self {
        let w = seed_sequence_state(seed);
        let initstate = (u128::from(w[0]) << 64) | u128::from(w[1]);
        let initseq = (u128::from(w[2]) << 64) | u128::from(w[3]);
        let mut g = Self {
            state: 0,
            inc: (initseq << 1) | 1,
            spare_u32: None,
        };
        g.step();
        g.state = g.state.wrapping_add(initstate);
        g.step();
        g
    }

    fn step(&mut self) {
        self.state = self.state.wrapping_mul(PCG_MULT).wrapping_add(self.inc);
    }

    /// The next 64-bit output (step, then XSL-RR).
    pub fn next_u64(&mut self) -> u64 {
        self.step();
        #[allow(clippy::cast_possible_truncation)]
        // the halves and the 6-bit rotation, by construction
        let (hi, lo, rot) = (
            (self.state >> 64) as u64,
            self.state as u64,
            (self.state >> 122) as u32,
        );
        (hi ^ lo).rotate_right(rot)
    }

    /// numpy's `pcg64_next32`: the low half of a fresh 64-bit output, its high half kept for the next call.
    pub fn next_u32(&mut self) -> u32 {
        if let Some(u) = self.spare_u32.take() {
            return u;
        }
        let next = self.next_u64();
        #[allow(clippy::cast_possible_truncation)] // the two halves, by construction
        {
            self.spare_u32 = Some((next >> 32) as u32);
            next as u32
        }
    }

    /// numpy's `random_bounded_uint64(0, rng)` for `rng` below 2^32: an integer in `[0, rng]` by Lemire's
    /// multiply-and-reject on 32-bit draws.
    fn bounded(&mut self, rng: u32) -> u32 {
        if rng == 0 {
            return 0;
        }
        if rng == u32::MAX {
            return self.next_u32();
        }
        let excl = rng + 1;
        let mut m = u64::from(self.next_u32()) * u64::from(excl);
        #[allow(clippy::cast_possible_truncation)] // the low 32 bits
        let mut leftover = m as u32;
        if leftover < excl {
            let threshold = (u32::MAX - rng) % excl;
            while leftover < threshold {
                m = u64::from(self.next_u32()) * u64::from(excl);
                #[allow(clippy::cast_possible_truncation)] // the low 32 bits
                {
                    leftover = m as u32;
                }
            }
        }
        #[allow(clippy::cast_possible_truncation)] // the high 32 bits
        {
            (m >> 32) as u32
        }
    }

    /// `Generator.choice(pop, size, replace=False)` for a population below 10,000 (Floyd's algorithm with numpy's
    /// open-addressing hash set, then a Fisher-Yates shuffle of the picks), draw for draw.
    ///
    /// # Panics
    /// `size` above `pop`, or a population beyond the 32-bit draws.
    pub fn choice_without_replacement(&mut self, pop: usize, size: usize) -> Vec<usize> {
        assert!(
            size <= pop && pop < 10_000,
            "choice: size {size} from a population of {pop}"
        );
        let mut idx = vec![0_usize; size];
        // the smallest power of two above 1.2 size, less one
        #[allow(
            clippy::cast_possible_truncation,
            clippy::cast_sign_loss,
            clippy::cast_precision_loss
        )]
        let set_size = (1.2 * size as f64) as u64;
        let mask = if set_size == 0 {
            0
        } else {
            u64::MAX >> set_size.leading_zeros()
        };
        let empty = u64::MAX;
        #[allow(clippy::cast_possible_truncation)] // a small set
        let m = mask as usize;
        let mut hash = vec![empty; m + 1];
        for j in pop - size..pop {
            #[allow(clippy::cast_possible_truncation)] // the population is below 10,000
            let val = u64::from(self.bounded(j as u32));
            #[allow(clippy::cast_possible_truncation)] // masked
            let mut loc = (val & mask) as usize;
            while hash[loc] != empty && hash[loc] != val {
                loc = (loc + 1) & m;
            }
            let pick = if hash[loc] == empty {
                hash[loc] = val;
                val
            } else {
                let j64 = j as u64;
                #[allow(clippy::cast_possible_truncation)] // masked
                let mut loc = (j64 & mask) as usize;
                while hash[loc] != empty {
                    loc = (loc + 1) & m;
                }
                hash[loc] = j64;
                j64
            };
            #[allow(clippy::cast_possible_truncation)] // below the population
            {
                idx[j + size - pop] = pick as usize;
            }
        }
        for i in (1..size).rev() {
            #[allow(clippy::cast_possible_truncation)] // the population is below 10,000
            let j = self.bounded(i as u32) as usize;
            idx.swap(i, j);
        }
        idx
    }

    /// `Generator.random()`: a double in [0, 1) from the top 53 bits.
    #[allow(clippy::cast_precision_loss)] // 53 bits are exact in a double
    pub fn random(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / 9_007_199_254_740_992.0)
    }
}
