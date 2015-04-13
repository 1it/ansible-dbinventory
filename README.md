# ansible-dbinventory
ansible [dynamic inventory](http://docs.ansible.com/intro_dynamic_inventory.html) script
providing sqlite3 backed management of hosts and groups through a curses interface.


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

By default, a sqlite3 database is created in <CWD>/.dbinventory.sqlite3. You may
specify the location of the database by providing **--db-path**, e.g.

```
dbinventory.py --db-create --db-path=/etc/ansible/hosts.sqlite3
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


Add a host, tag, or tag group
-----------------------------


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
* do not import [new] duplicates
* fix height issue 
* allow reselection of edited host/tag
