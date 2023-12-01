#!/usr/bin/env sh

set -e -o errexit

# This command builds the latest version of the app
poetry build

# - `ls -rt dist/*.whl`: lists all the `.whl` files in the `dist` directory.
# The `-r` option reverses the order of the files, and the `-t` sorts the files by modification time.
# So, this command will list all the `.whl` files in the `dist` directory in ascending order of modification time
# (i.e., the most recently modified file will be last).
# - `tail -n 1`: gets the last line of output from the previous command. In this context, it will get the most recently modified `.whl` file.
# - `basename`: removes the path from a pathname string, leaving just the filename. In this context, it will remove the `dist/` part from the filename.
# - `LATEST_VERSION=$(...)`: assigns the output of the command inside the parentheses to the variable `LATEST_VERSION`.

# So, in summary, this line gets the filename of the latest build
LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))

# User must set this to the user of the remote machine (Raspberry Pi)
# This is typically `pi` by default but some users may opt not install the pi user
UBO_USER=ubo

# this command copies the latest build file to the remote machine under /temp/
scp dist/$LATEST_VERSION $UBO_USER@ubo-development-pod:/tmp/

# --deps flag is specficied, then ssh to remote device, activate virtual environment, and install the lastest build
test "$deps" == "True" && ssh $UBO_USER@ubo-development-pod "source ubo-app/bin/activate && pip install --upgrade /tmp/$LATEST_VERSION[default]"
# run ubo app after upgrading it
ssh $UBO_USER@ubo-development-pod "source \$HOME/.profile && source /etc/profile && source ubo-app/bin/activate && pip install --upgrade --force-reinstal --no-deps /tmp/$LATEST_VERSION && (sudo killall ubo -9 || true) && sudo \$(which ubo)"
