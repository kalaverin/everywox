# EveryWox, a Wox plugin for Everything search engine

## Configure Rust toolchain

0. Install [Rust/Cargo toolchain](https://win.rustup.rs/x86_64) if you don't have it yet.

1. Update (or install) your Cargo tooling by `rustup update`.

2. Press Win-Q, enter search query „View advanced system settings“, and open it; go to „Advanced“ tab, and click „Environment Variables...“ button.

3. Edit `Path` variable in your user variables, and add path to your Cargo bin directory, usually it is `%USERPROFILE%\.cargo\bin`, it's where `cargo.exe` and `rustc.exe` are located.

3. Install (or update) offline compilation cache tool `sccache` by `cargo install sccache==0.9.1` (of cource, you always can use latest version, but I tested only this one).

4. To user variables, add RUSTC_WRAPPER environment variable with `sccache.exe` value (it's also located in cargo home binaries directory).

5. You can check that sccache is working by running `sccache -s` command in new terminal window, it should show you some stats, even if they are all zeros.

5. Force update (or install) your mise toolchain by `cargo install -f mise`.

### Optional steps

6. Also install cargo packaging upgrade tool by run 'cargo install cargo-update'.

7. After it you can upgrade all packages by `cargo install-update --all`.

## Configure EveryWox plugin

1. Update in const.py `WOX_SDK_PATH=` to your local path of Wox SDK (directory that contains wox.py)

2. Run `mise install` to install dependencies.

3. Get absolute path of virtuan environment Scripts directory, e.g. `d:/apps/utils/ergo/wox/plugins/everywox/.venv.nt/scripts/` without file name.

4. Set it in Wox settings as Python Path.

5. *DISABLE* "Wox builtin Everything" plugin if you have Everything plugin installed.

6. Enable this plugin in Wox settings.

7. Restart Wox, have fun!
