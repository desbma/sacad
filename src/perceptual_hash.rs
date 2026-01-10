//! Perceptual hash

use anyhow::Context as _;

/// Image perceptual hash
#[cfg(any(feature = "ahash", feature = "dhash"))]
pub(crate) struct PerceptualHash(u64);
#[cfg(feature = "blockhash")]
pub(crate) struct PerceptualHash(blockhash::Blockhash64);

impl PerceptualHash {
    /// Compute hash from undecoded image buffer
    #[cfg(feature = "ahash")]
    pub(crate) fn from_image_buffer(buf: &[u8]) -> anyhow::Result<Self> {
        // https://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html

        const PERCEPTUAL_HASH_IMG_SIZE: u32 = 8;

        // Decode & resize image
        let img = image::load_from_memory(buf)
            .context("Failed to decode thumbnail")?
            .resize_exact(
                PERCEPTUAL_HASH_IMG_SIZE,
                PERCEPTUAL_HASH_IMG_SIZE,
                image::imageops::FilterType::Lanczos3,
            )
            .to_luma8();

        // Compute hash
        let pixels = img.as_raw();
        #[expect(clippy::cast_possible_truncation)]
        let mean = (pixels.iter().map(|v| u64::from(*v)).sum::<u64>() / pixels.len() as u64) as u8;
        let hash = pixels
            .iter()
            .enumerate()
            .fold(0_u64, |mut hash, (i, pixel)| {
                if *pixel > mean {
                    hash |= 1 << i;
                }
                hash
            });

        Ok(Self(hash))
    }
    #[cfg(feature = "dhash")]
    pub(crate) fn from_image_buffer(buf: &[u8]) -> anyhow::Result<Self> {
        // See https://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html

        const PERCEPTUAL_HASH_IMG_SIZE: (u32, u32) = (9, 8);

        // Decode & resize image
        let img = image::load_from_memory(buf)
            .context("Failed to decode thumbnail")?
            .resize_exact(
                PERCEPTUAL_HASH_IMG_SIZE.0,
                PERCEPTUAL_HASH_IMG_SIZE.1,
                image::imageops::FilterType::Lanczos3,
            )
            .to_luma8();

        // Compute hash
        let pixels = img.as_raw();
        let mut hash = 0;
        for row in 0..PERCEPTUAL_HASH_IMG_SIZE.1 {
            let start = (row * PERCEPTUAL_HASH_IMG_SIZE.0) as usize;
            let end = ((row + 1) * PERCEPTUAL_HASH_IMG_SIZE.0) as usize;
            #[expect(clippy::indexing_slicing)]
            for (i, ps) in pixels[start..end].windows(2).enumerate() {
                debug_assert!(i < 8);
                if ps[0] < ps[1] {
                    hash |= 1 << (u64::from(row) * 8 + i as u64);
                }
            }
        }

        Ok(Self(hash))
    }
    #[cfg(feature = "blockhash")]
    pub(crate) fn from_image_buffer(buf: &[u8]) -> anyhow::Result<Self> {
        // Decode image
        let img = image::load_from_memory(buf).context("Failed to decode thumbnail")?;

        // Compute hash
        let hash = blockhash::blockhash64(&img);
        Ok(Self(hash))
    }

    /// Return true if both hashes seem to refer to a similar image
    #[cfg(any(feature = "ahash", feature = "dhash"))]
    pub(crate) fn is_similar(&self, other: &Self) -> bool {
        const MAX_HAMMING_DELTA: u32 = if cfg!(feature = "ahash") { 5 } else { 8 };
        (self.0 ^ other.0).count_ones() < MAX_HAMMING_DELTA
    }
    #[cfg(feature = "blockhash")]
    pub(crate) fn is_similar(&self, other: &Self) -> bool {
        const MAX_HAMMING_DELTA: u32 = 2;
        self.0.distance(&other.0).count_ones() < MAX_HAMMING_DELTA
    }

    #[cfg(test)]
    #[cfg(any(feature = "ahash", feature = "dhash"))]
    pub(crate) fn test_similar() -> Self {
        Self(0)
    }

    #[cfg(test)]
    #[cfg(feature = "blockhash")]
    pub(crate) fn test_value1() -> Self {
        Self(blockhash::Blockhash64::from([0; 8]))
    }

    #[cfg(test)]
    #[cfg(any(feature = "ahash", feature = "dhash"))]
    pub(crate) fn test_dissimilar() -> Self {
        Self(u64::MAX)
    }

    #[cfg(test)]
    #[cfg(feature = "blockhash")]
    pub(crate) fn test_value2() -> Self {
        Self(blockhash::Blockhash64::from([0xFF; 8]))
    }
}
