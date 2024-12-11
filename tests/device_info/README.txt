This folder contains golden device info returned from blueair AWS servers.

The content of the text file is the first element of the deviceInfo field of
the response from the initial get info API call, dumped as a Python object
with pprint.pprint.

TODO(dahlb): This is not very smooth consider update the logging system
to produces exactly this structure as a json object and update all of the
goldens as json files.

