# ansible-dbinventory
dbinbventory is a [ansible dynamic inventory script](http://docs.ansible.com/intro_dynamic_inventory.html)
that provides an alternative to .ini file editing. It simplifies and speeds up expanding inventories (host and group management) by combining a CLI UI, JSON I/O, and sqlite storage.


![curses interface](docs/screenshots/ansible-dbinventory-npyscreen.png?raw=true)


Requirements
------------

* Python 2.5+
* [sqlalchemy](https://pypi.python.org/pypi/SQLAlchemy)
* [pycrypto](https://pypi.python.org/pypi/pycrypto)

OPTIONAL - for curses interface
* [npyscreen](https://pypi.python.org/pypi/npyscreen/)


Usage
=====

Create the initial database
---------------------------

```
dbinventory.py --db-create
```


Creates a file named {CWD}/.dbinventory.sqlite3




You may specify the the database location with a **--db-path** 
argument ,or, through the **DBINVENTORY_PATH** environment variable. E.g.

```
dbinventory.py --db-create --db-path=/ansible/hosts.sqlite3

-- or --

export DBINVENTORY_PATH="/ansible/hosts.sqlite3" && dbinventory.py --db-create
```



**HINT** : 

by default dbinventory  looks for a database file named `{CWD}/.{SCRIPT_NAME}.sqlite3`.

This is important because it allows you to follow [ansible best practices](https://docs.ansible.com/playbooks_best_practices.html).
 -- __keeping a unique inventory file PER ENVIRONMENT__.  E.g.
 
 ```sh
 cp dbinventory.py {production.py,staging.py}
 ./staging.py --db-create --db-import staging/hosts.json
 ./production.py --db-create --db-import production/hosts.json
 
 ./staging.py -e
 # will open management interface for hosts backed by ./staging.sqlite3
 
 ```



Bulk import hosts, vars, and tags from a JSON source
----------------------------------------------------


```
dbinventory.py --db-import /path/to/data.json
```

Atomically applies entities from a JSON file. Currently the best method for
bulk management. An example file is provided in [test-data/initial-data.json](test-data/initial-data.json).

Additionally, you may export the database data in a format that can be imported:

```
dbinventory.py --db-export > /path/to/data.json
```


Manage Hosts
------------


In dbinventory, "Tags" belong to "Tag Groups", and may belong to any number of
"Hosts". 

"Tags" are essentially ansible "inventory groups", and "Tag Groups" act
as a taxonomy to organize tags in the interface (not used by ansible at all).

Tag names must be unique (e.g. you cannot have two tags named "sla" even if 
they belong to a different Tag Group).


```
db-inventory.py --add-group <Tag Group Name>
db-inventory.py --add-tag <Tag Name>
db-inventory.py --add-host <Host>
```

SSH Config compatible Output 
----------------------------

You may use dbinventory to generate ssh config files as well.

```
db-inventory.py --ssh-config >> ~/.ssh/config
cat ~/.ssh/config
##### dbinventory hosts #####
#############################

## ACME-db1 groups: ACME, dec, mysql
Host ACME-db1
HostName 8.8.8.9
User roadrunner

## ACME-web1 groups: ACME, dec, magento, redis
Host ACME-web1
HostName 8.8.8.8
User roadrunner

## rabbit-web1 groups: bin, magento, sla
Host rabbit-web1
User bugs

## rabbit-web2 groups: magento
Host rabbit-web2
User bugs 
```



Sensitive Data
--------------

You may store the ssh and sudo password used to interract with a host. Their
values are encrypted using an AES symmetric key -- and may *only be accessed
if dbinventory is called with the --db-secret flag (or the DBINVENTORY_SECRET
environmental variable is set)*. If you do not provide a secret, these fields
will not appear in results or be editable in forms.


```
db-inventory.py --add-host <Host> --db-secret="super secret password"
```

alternatively, use a persistent environment variable

```
export DBINVENTORY_SECRET="super secret password"
db-inventory.py --host <Host>
```


NOTE: The first time dbinventory accesses a database using a secret key, a known
value is encoded. Subsequent calls decrypt and test the known value for a
match. If your secret does not match the secret stored in the database, dbinventory
will complain and exit. This is meant to provent a operator misspellings of 
the secret, which could result in unretrievable data.


Development
===========

TODO:

* finish tag + group editing
* fix height issue 
* allow reselection of edited host/tag
