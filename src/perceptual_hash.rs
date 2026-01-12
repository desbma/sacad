//! Perceptual hash

use anyhow::Context as _;

/// Image perceptual hash
pub(crate) struct PerceptualHash(blockhash::Blockhash64);

impl PerceptualHash {
    /// Compute hash from undecoded image buffer
    pub(crate) fn from_image_buffer(buf: &[u8]) -> anyhow::Result<Self> {
        // Decode image
        let img = image::load_from_memory(buf).context("Failed to decode thumbnail")?;

        // Compute hash
        let hash = blockhash::blockhash64(&img);
        Ok(Self(hash))
    }

    /// Return true if both hashes seem to refer to a similar image
    pub(crate) fn is_similar(&self, other: &Self) -> bool {
        const MAX_HAMMING_DELTA: u32 = 2;
        self.0.distance(&other.0).count_ones() < MAX_HAMMING_DELTA
    }

    #[cfg(test)]
    pub(crate) fn test_value1() -> Self {
        Self(blockhash::Blockhash64::from([0; 8]))
    }

    #[cfg(test)]
    pub(crate) fn test_value2() -> Self {
        Self(blockhash::Blockhash64::from([0xFF; 8]))
    }
}
