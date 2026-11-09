// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//! H.264 of the embedded RDP client on Linux through Cisco's OpenH264 binary (R-1102,
//! docs/features/kern-rdp-5.md). Cisco's patent licence covers only its own binary, downloaded to
//! the device apart from the app (https://www.openh264.org/BINARY_LICENSE.txt), so the desktop
//! fetches exactly one release, checks its SHA-256 against the value pinned here and keeps it in
//! the app data dir. Before each load the desktop checks the file once more against the same pin,
//! as `openh264-sys2`'s own list of known hashes stops at 2.6.0 (docs/features/kern-rdp-6.md). The
//! library is loaded at runtime; OpenH264 built from source stays out (license_gate.rs).

use std::fmt::Write as _;
use std::fs;
use std::io::{self, Read, Write as _};
use std::path::{Path, PathBuf};
use std::time::Duration;

use ironrdp_client::h264::H264DecoderFactory;
use ironrdp_egfx::decode::{H264Decoder, OpenH264Decoder, YuvMatrix};
use openh264::OpenH264API;
use sha2::{Digest, Sha256};

use crate::http_client;

/// The one release the desktop loads, ABI 8 like the 2.6.0 that `openh264` 0.9 is built against;
/// the round trip below proves the bindings fit it.
const URL: &str = "https://ciscobinary.openh264.org/libopenh264-2.7.0-linux64.8.so.bz2";
/// SHA-256 of the unpacked library, as in Cisco's libopenh264-2.7.0-linux64.8.so.signed.sha256.txt
/// next to it and in two downloads of our own (checked 2026-11-09).
const SHA256: &str = "1522f873a482923c5ec018a4415e1866898197528828c50f90fd300c94620df3";
const FILE_NAME: &str = "libopenh264-2.7.0-linux64.8.so";
/// Every release the desktop ever kept starts so; an older one goes once the pinned one is there.
const FILE_PREFIX: &str = "libopenh264-";
/// The folder in the app data dir; nothing else lives in it.
const DIR_NAME: &str = "openh264";
/// About 0.6 MB packed and 1.7 MB unpacked; the limits only stop a runaway answer.
const MAX_PACKED: usize = 4 * 1024 * 1024;
const MAX_UNPACKED: usize = 8 * 1024 * 1024;
/// How long the start of a session waits for the download; a session that misses it runs
/// without H.264 and the next one tries again.
pub(crate) const FETCH_DEADLINE: Duration = Duration::from_secs(15);

fn library_dir(base: &Path) -> PathBuf {
    base.join(DIR_NAME)
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .fold(String::with_capacity(64), |mut hex, byte| {
            let _ = write!(hex, "{byte:02x}");
            hex
        })
}

/// The library in `dir`, if it is there and has the pinned hash.
fn verified(dir: &Path) -> Option<PathBuf> {
    let path = dir.join(FILE_NAME);
    let bytes = fs::read(&path).ok()?;
    (sha256_hex(&bytes) == SHA256).then_some(path)
}

/// Unpacks `packed`, checks the pinned hash and writes the library to `dir` through a temporary
/// file, so a half-written library never carries the final name. Nothing is written when the hash
/// differs.
fn install(dir: &Path, packed: &[u8]) -> Result<PathBuf, String> {
    let mut library = Vec::new();
    bzip2::read::BzDecoder::new(packed)
        .take(MAX_UNPACKED as u64 + 1)
        .read_to_end(&mut library)
        .map_err(|error| format!("the OpenH264 download is no bzip2 file: {error}"))?;
    if library.len() > MAX_UNPACKED {
        return Err("the unpacked OpenH264 library is too large".to_string());
    }
    let hash = sha256_hex(&library);
    if hash != SHA256 {
        return Err(format!(
            "the OpenH264 library has an unknown SHA-256 {hash}"
        ));
    }
    fs::create_dir_all(dir).map_err(|error| format!("cannot create {}: {error}", dir.display()))?;
    let path = dir.join(FILE_NAME);
    let part = dir.join(format!(".{FILE_NAME}.part-{}", std::process::id()));
    let written = write_private(&part, &library).and_then(|()| fs::rename(&part, &path));
    if let Err(error) = written {
        let _ = fs::remove_file(&part);
        return Err(format!("cannot write {}: {error}", path.display()));
    }
    Ok(path)
}

fn write_private(path: &Path, bytes: &[u8]) -> io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

async fn download() -> Result<Vec<u8>, String> {
    let client = http_client::with_timeouts(reqwest::Client::builder())
        .https_only(true)
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|error| format!("cannot build the HTTP client: {error}"))?;
    let response = client
        .get(URL)
        .send()
        .await
        .map_err(|error| format!("cannot reach {URL}: {error}"))?;
    if !response.status().is_success() {
        return Err(format!("{URL} answered {}", response.status()));
    }
    http_client::read_bounded(response, MAX_PACKED, "OpenH264 library")
        .await
        .map_err(|error| error.to_string())
}

/// The checked library in the app data dir `base`, downloaded first when it is missing or
/// differs from the pinned one; older releases in the folder go.
pub(crate) async fn ensure(base: &Path) -> Result<PathBuf, String> {
    let dir = library_dir(base);
    let path = match verified(&dir) {
        Some(path) => path,
        None => {
            let packed = tokio::time::timeout(FETCH_DEADLINE, download())
                .await
                .map_err(|_| {
                    format!("the OpenH264 download took longer than {FETCH_DEADLINE:?}")
                })??;
            install(&dir, &packed)?
        }
    };
    prune(&dir);
    Ok(path)
}

/// Deletes the releases in `dir` other than the pinned one, which an older app left there.
fn prune(dir: &Path) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with(FILE_PREFIX) && name != FILE_NAME {
            if let Err(error) = fs::remove_file(entry.path()) {
                log::warn!("cannot delete the old OpenH264 library {name}: {error}");
            }
        }
    }
}

/// Loads the library at `path` only if it still has the pinned hash. `openh264-sys2` would check
/// against its own list, which does not carry the pinned release.
fn load(path: &Path) -> Result<OpenH264API, String> {
    let bytes =
        fs::read(path).map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let hash = sha256_hex(&bytes);
    if hash != SHA256 {
        return Err(format!(
            "the OpenH264 library has an unknown SHA-256 {hash}"
        ));
    }
    // SAFETY: the file is the pinned Cisco release for linux64 with the ABI of the bindings (the
    // round trip test loads it), which is what from_blob_path_unchecked asks of its caller.
    unsafe { OpenH264API::from_blob_path_unchecked(path) }
        .map_err(|error| format!("cannot load {}: {error}", path.display()))
}

/// Deletes the library and its folder from the app data dir `base`; none there is no error.
pub(crate) fn remove(base: &Path) -> io::Result<()> {
    match fs::remove_dir_all(library_dir(base)) {
        Err(error) if error.kind() != io::ErrorKind::NotFound => Err(error),
        _ => Ok(()),
    }
}

/// A decoder from the library at `path` for each surface and video; a decoder that fails to
/// start leaves that surface without H.264 and the server falls back to the other codecs.
pub(crate) fn decoder_factory(path: PathBuf) -> H264DecoderFactory {
    H264DecoderFactory::new(move || {
        match load(&path)
            .and_then(|api| OpenH264Decoder::from_api(api).map_err(|error| error.to_string()))
        {
            // MS-RDPEVOR video is converted from RGB with BT.601 (2.2.1.6), as IronRDP's own
            // OpenH264 factory does; the graphics pipeline converts the YUV planes itself.
            Ok(decoder) => {
                Some(Box::new(decoder.with_yuv_matrix(YuvMatrix::Bt601Limited))
                    as Box<dyn H264Decoder>)
            }
            Err(error) => {
                log::warn!("OpenH264 does not start: {error}");
                None
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use openh264::encoder::{Encoder, EncoderConfig};
    use openh264::formats::{RgbaSliceU8, YUVBuffer};

    struct Scratch(PathBuf);

    impl Scratch {
        fn new(name: &str) -> Self {
            let dir = std::env::temp_dir().join(format!(
                "ah-openh264-{name}-{}-{:?}",
                std::process::id(),
                std::thread::current().id()
            ));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).unwrap();
            Scratch(dir)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn packed(bytes: &[u8]) -> Vec<u8> {
        let mut encoder = bzip2::write::BzEncoder::new(Vec::new(), bzip2::Compression::default());
        encoder.write_all(bytes).unwrap();
        encoder.finish().unwrap()
    }

    fn entries(dir: &Path) -> Vec<String> {
        match fs::read_dir(dir) {
            Ok(read) => read
                .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
                .collect(),
            Err(_) => Vec::new(),
        }
    }

    #[test]
    fn install_refuses_another_library_and_writes_nothing() {
        let scratch = Scratch::new("hash");
        let dir = library_dir(&scratch.0);
        let error = install(&dir, &packed(b"not the library")).unwrap_err();
        assert!(error.contains("unknown SHA-256"), "{error}");
        assert!(entries(&dir).is_empty(), "{:?}", entries(&dir));
        assert_eq!(verified(&dir), None);
    }

    #[test]
    fn install_refuses_what_is_no_bzip2() {
        let scratch = Scratch::new("bz2");
        let dir = library_dir(&scratch.0);
        let error = install(&dir, b"<html>not found</html>").unwrap_err();
        assert!(error.contains("no bzip2"), "{error}");
        assert!(entries(&dir).is_empty());
    }

    #[test]
    fn install_stops_unpacking_past_the_limit() {
        let scratch = Scratch::new("bomb");
        let dir = library_dir(&scratch.0);
        let error = install(&dir, &packed(&vec![0; MAX_UNPACKED + 1])).unwrap_err();
        assert!(error.contains("too large"), "{error}");
        assert!(entries(&dir).is_empty());
    }

    #[test]
    fn a_library_with_another_hash_on_disk_is_not_taken() {
        let scratch = Scratch::new("tampered");
        let dir = library_dir(&scratch.0);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(FILE_NAME), b"changed on disk").unwrap();
        assert_eq!(verified(&dir), None);
    }

    #[test]
    fn load_refuses_a_library_with_another_hash() {
        let scratch = Scratch::new("load");
        let path = scratch.0.join(FILE_NAME);
        fs::write(&path, b"changed on disk").unwrap();
        let error = load(&path).err().expect("not loaded");
        assert!(error.contains("unknown SHA-256"), "{error}");
        assert!(load(&scratch.0.join("missing.so")).is_err());
    }

    #[test]
    fn prune_keeps_only_the_pinned_release() {
        let scratch = Scratch::new("prune");
        let dir = library_dir(&scratch.0);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(FILE_NAME), b"x").unwrap();
        fs::write(dir.join("libopenh264-2.6.0-linux64.8.so"), b"old").unwrap();
        // A download another call is writing right now stays.
        let part = format!(".{FILE_NAME}.part-1");
        fs::write(dir.join(&part), b"half").unwrap();
        prune(&dir);
        let mut left = entries(&dir);
        left.sort();
        assert_eq!(left, vec![part, FILE_NAME.to_string()]);
        prune(&scratch.0.join("missing"));
    }

    #[test]
    fn remove_deletes_the_folder_and_is_quiet_without_one() {
        let scratch = Scratch::new("remove");
        let dir = library_dir(&scratch.0);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(FILE_NAME), b"x").unwrap();
        remove(&scratch.0).unwrap();
        assert!(!dir.exists());
        remove(&scratch.0).unwrap();
        assert!(scratch.0.exists(), "the app data dir itself stays");
    }

    // Cisco's real binary, fetched from ciscobinary.openh264.org: the download, the pinned hash,
    // the load after our own hash check, an older release that goes, and a picture that goes
    // through its encoder and comes back from the decoder the sessions use.
    #[tokio::test]
    async fn ciscos_library_downloads_loads_and_decodes_a_picture() {
        let scratch = Scratch::new("cisco");
        let dir = library_dir(&scratch.0);
        fs::create_dir_all(&dir).unwrap();
        fs::write(
            dir.join("libopenh264-2.6.0-linux64.8.so"),
            b"left by an older app",
        )
        .unwrap();
        let path = ensure(&scratch.0).await.expect("download and install");
        assert_eq!(path, library_dir(&scratch.0).join(FILE_NAME));
        assert_eq!(
            entries(&library_dir(&scratch.0)),
            vec![FILE_NAME.to_string()]
        );
        assert_eq!(
            ensure(&scratch.0).await.unwrap(),
            path,
            "the second call keeps the file"
        );

        let (width, height) = (64u32, 64u32);
        let rgba: Vec<u8> = (0..width * height)
            .flat_map(|i| [(i % 256) as u8, 0x80, 0x40, 0xFF])
            .collect();
        let api = load(&path).expect("load");
        let mut encoder = Encoder::with_api_config(api, EncoderConfig::new()).expect("encoder");
        let picture =
            YUVBuffer::from_rgb_source(RgbaSliceU8::new(&rgba, (width as usize, height as usize)));
        let stream = encoder.encode(&picture).expect("encode").to_vec();
        assert!(!stream.is_empty());

        let mut decoder = decoder_factory(path).create().expect("decoder");
        let frame = decoder.decode(&stream).expect("decode");
        assert!(frame.width() >= width && frame.height() >= height);
        // Lossy, but the green and blue of the picture survive.
        let (g, b) = (frame.data()[1], frame.data()[2]);
        assert!(
            (0x70..=0x90).contains(&g) && (0x30..=0x50).contains(&b),
            "{g:#x} {b:#x}"
        );
    }
}
