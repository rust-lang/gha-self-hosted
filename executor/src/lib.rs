use anyhow::{Error, bail};
use serde::Deserializer;
use serde::de::{Deserialize, Error as _};

mod credential_server;
pub mod github;
pub mod images;
pub mod qemu;
mod qmp;

#[derive(serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
pub struct InstanceSpec {
    pub label: String,
    pub image: String,
    pub arch: InstanceArch,
    pub cpu_cores: u32,
    pub ram: Size,
    pub root_disk: Size,
    pub timeout_seconds: u32,
}

#[derive(serde::Deserialize, Clone, Copy)]
pub enum InstanceArch {
    #[serde(rename = "x86_64")]
    X86_64,
    #[serde(rename = "aarch64")]
    Aarch64,
}

#[derive(Clone, Copy, Debug)]
pub struct Size {
    value: u64,
    unit: SizeUnit,
}

impl std::str::FromStr for Size {
    type Err = Error;

    fn from_str(input: &str) -> Result<Self, Self::Err> {
        let Some((amount_end, unit)) = input.char_indices().last() else {
            bail!("empty unit");
        };
        Ok(Size {
            value: (&input[..amount_end]).parse()?,
            unit: match unit {
                'k' | 'K' => SizeUnit::Kilobytes,
                'm' | 'M' => SizeUnit::Megabytes,
                'g' | 'G' => SizeUnit::Gigabytes,
                't' | 'T' => SizeUnit::Terabytes,
                _ => bail!("invalid unit: {unit}"),
            },
        })
    }
}

impl std::fmt::Display for Size {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let value = self.value;
        let unit = match self.unit {
            SizeUnit::Kilobytes => 'k',
            SizeUnit::Megabytes => 'M',
            SizeUnit::Gigabytes => 'G',
            SizeUnit::Terabytes => 'T',
        };
        write!(f, "{value}{unit}")
    }
}

impl<'de> Deserialize<'de> for Size {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let string = String::deserialize(deserializer)?;
        Ok(string
            .parse::<Size>()
            .map_err(|e| D::Error::custom(e.to_string()))?)
    }
}

#[derive(Clone, Copy, Debug)]
pub enum SizeUnit {
    Kilobytes,
    Megabytes,
    Gigabytes,
    Terabytes,
}
