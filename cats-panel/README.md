# Illawarra Line CATS Panel

Dispatcher Panel for [The Illawarra Line](https://illawarraline.net) HO Scale Model railroad.

## Requirements

- JMRI 5.4
- CATS 3.0

## File Structure

```bash
│   └── resources
│       └── signals
│           └── cats-masts
│               ├── appearance-cats-virtual.xml
│               ├── aspects.xml
│               └── index.shtml
├── panel.xml
├── masts.xml

```

- .jmri: Supporting files to support the CATS-specific signal masts in JMRI
- panel.xml: The CATS Panel XML file.

## Install Guide

- Install specified CATS and JMRI Version, create a profile connecting to the MQTT Broker.
- Clone this repo
- Copy the contents of the .jmri folder to your JMRI profile folder - eg for mac: `/Users/<username>/Library/Preferences/JMRI/<ProfileName>.jmri/`
- configure your JMRI during start to load the masts.xml file
- start the panel with the cats script: `cats.csh /Path/To/Repo/panel.xml`
