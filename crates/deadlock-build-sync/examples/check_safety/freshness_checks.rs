use std::fs;
use std::io::{BufRead as _, BufReader, Write as _};
use std::net::{TcpListener, TcpStream};
use std::thread;
use std::time::{Duration, Instant};

use deadlock_build_sync::install_catalog;
use deadlock_data::{Error, Result};
use deadlock_guides::HeroBuildCatalog;
use deadlock_input::parse_patch_feed;
use deadlock_steam::{CacheLocation, read_cache};
use serde_json::{Value, json};

pub fn check_installation_freshness() -> Result<()> {
    check_hero_release_feed()?;
    let root = tempfile::tempdir()?;
    let location = CacheLocation {
        account_id: 7,
        cache_path: root.path().join("cached_hero_builds.kv3"),
        app_directory: root.path().into(),
    };
    fs::write(&location.cache_path, b"invalid reference cache")?;
    let cache_error = read_cache(&location.cache_path)
        .err()
        .ok_or_else(|| Error::new("Reference cache must fail parsing"))?
        .to_string();
    let patches = json!([{
        "title":"Reference patch",
        "pub_date":"2026-10-10T00:00:00Z",
        "content":"Reference changes",
    }]);
    let mut catalog: HeroBuildCatalog = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/imbue-catalog.json"
    ))?;
    catalog.patch = parse_patch_feed(&patches, None)?.to_document()?;
    for (case, expected) in [
        ("current", cache_error.as_str()),
        ("client", "Hero builds use another client version"),
        ("patch", "Hero builds use another patch"),
        ("unavailable", "HTTP status 403"),
    ] {
        let mut selected = catalog.clone();
        if case == "client" {
            selected.client_version += 1;
        } else if case == "patch" {
            selected.patch.insert("identity".into(), "obsolete".into());
        }
        check_rejected_installation(
            &location,
            &selected,
            &patches,
            expected,
            case == "unavailable",
        )?;
    }
    catalog.schema_version = 0;
    require_installation_error(
        &location,
        &catalog,
        "invalid URL",
        "another schema or method",
    )?;
    if fs::read(&location.cache_path)? != b"invalid reference cache"
        || fs::read_dir(root.path())?.count() != 1
    {
        return Err(Error::new(
            "Rejected installation changed the temporary cache",
        ));
    }
    Ok(())
}

fn check_rejected_installation(
    location: &CacheLocation,
    catalog: &HeroBuildCatalog,
    patches: &Value,
    expected: &str,
    unavailable: bool,
) -> Result<()> {
    let responses = if unavailable {
        vec![("/v1/assets/client-versions", 403, Value::Null)]
    } else {
        vec![
            ("/v1/assets/client-versions", 200, json!([1])),
            ("/v2/patches", 200, patches.clone()),
        ]
    };
    let listener = TcpListener::bind("127.0.0.1:0")?;
    listener.set_nonblocking(true)?;
    let base_url = format!("http://{}", listener.local_addr()?);
    let server = thread::spawn(move || -> Result<()> {
        for (path, status, response) in responses {
            let stream = accept_request(&listener)?;
            respond(stream, path, status, &response)?;
        }
        Ok(())
    });
    let result = require_installation_error(location, catalog, &base_url, expected);
    server
        .join()
        .map_err(|_| Error::new("Reference API thread failed"))??;
    result
}

fn require_installation_error(
    location: &CacheLocation,
    catalog: &HeroBuildCatalog,
    base_url: &str,
    expected: &str,
) -> Result<()> {
    match install_catalog(location, catalog, "Reference player", base_url) {
        Err(error) if error.to_string().contains(expected) => Ok(()),
        result => Err(Error::new(format!(
            "Installation did not return {expected}: {result:?}"
        ))),
    }
}

fn accept_request(listener: &TcpListener) -> Result<TcpStream> {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match listener.accept() {
            Ok((stream, _)) => return Ok(stream),
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                if Instant::now() >= deadline {
                    return Err(Error::new("Installation did not request the reference API"));
                }
                thread::sleep(Duration::from_millis(10));
            }
            Err(error) => return Err(error.into()),
        }
    }
}

fn respond(mut stream: TcpStream, path: &str, status: u16, document: &Value) -> Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
    stream.set_write_timeout(Some(Duration::from_secs(2)))?;
    let mut reader = BufReader::new(&mut stream);
    let mut request = String::new();
    reader.read_line(&mut request)?;
    if request.split_whitespace().nth(1) != Some(path) {
        return Err(Error::new(format!(
            "Unexpected reference API request: {request}"
        )));
    }
    loop {
        let mut header = String::new();
        if reader.read_line(&mut header)? == 0 || header == "\r\n" {
            break;
        }
    }
    let body = serde_json::to_vec(document)?;
    write!(
        stream,
        "HTTP/1.1 {status} Reference\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )?;
    stream.write_all(&body)?;
    Ok(())
}

/// A hero release post is not a patch. The latest post with the word "update" is the patch.
fn check_hero_release_feed() -> Result<()> {
    let update = json!({
        "title":" Minor Update - 10-05-2026",
        "pub_date":"2026-10-05T23:05:32Z",
        "content":"- Rat King: Scrap Grenade - Damage increased from 65 to 70",
    });
    let release = json!({
        "title":"Fairfax Industries Employee Spotlight",
        "pub_date":"2026-10-13T20:59:55Z",
        "content":"Today, Fairfax Industries is proud to introduce their most valuable salesman.",
    });
    let both = json!([release, update]);
    if parse_patch_feed(&both, None)?.title != " Minor Update - 10-05-2026" {
        return Err(Error::new("A hero release post replaced the current patch"));
    }
    if parse_patch_feed(&json!([release]), None)?.title != "Fairfax Industries Employee Spotlight" {
        return Err(Error::new(
            "A feed without updates did not use its latest post",
        ));
    }
    Ok(())
}
