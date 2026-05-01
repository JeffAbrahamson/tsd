
jeff@vogel:~ $ tsd chocolat-michel-cluizel init
Traceback (most recent call last):
  File "/home/jeff/bin/tsd.py", line 590, in <module>
    main()
  File "/home/jeff/bin/tsd.py", line 584, in main
    value = float(args.args[1])
ValueError: could not convert string to float: 'init'
1, jeff@vogel:~ $ tsd chocolat-michel-cluizel --init
Series "chocolat-michel-cluizel" exists, creation not permitted.
1, jeff@vogel:~ $ tsd chocolat-michel-cluizel 
Series "chocolat-michel-cluizel" does not exist, use init to create.
1, jeff@vogel:~ $




jeff@vogel:~ $ tsd tea -b 1 730
usage: tsd.py [-h] [--verbose] [--version] [--date DATE] [--days-before DAYS_BEFORE] [--diff] [--list] [--edit] [--config]
              [--series-dir SERIES_DIR] [--init] [--plot]
              [args ...]
tsd.py: error: unrecognized arguments: 730
2, jeff@vogel:~ $



