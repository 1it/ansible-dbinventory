#!/usr/bin/env python
from pprint import pprint
from sqlalchemy.orm import relationship

# blueacorn host manager 
# https://bitbucket.org/zzzeek/sqlalchemy/wiki/UsageRecipes/SymmetricEncryption


'''
BlueAcorn external inventory script
===================================

Generates Ansible inventory backed by an sqlite database

Based on https://github.com/geerlingguy/ansible-for-devops/tree/master/dynamic-inventory/digitalocean

In addition to the --list and --host options used by Ansible, there are options
for managing and printing passwords. Passwords are stored using AES symmetric
encryption and can only be retrieved by providing the correct secret. 

'''

######################################################################

import os
import sys
import re
import argparse
from time import time
import ConfigParser

try:
    import json
except ImportError:
    import simplejson as json

try:
    from sqlalchemy import create_engine, inspect, Column, Integer, String, Enum, ForeignKey, TypeDecorator
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import Session
except ImportError, e:
    print "failed=True msg='`sqlalchemy` library required for this script'"
    sys.exit(1)

try:
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    import hashlib
    import binascii
    CRYPTO_ENABLED = False
    AES_KEY = None

    
except ImportError, e:
    print "failed=True msg='`pycrypto` library required for this script'"
    sys.exit(1)
    
try:
    import npyscreen
    import curses
    UI_ENABLED = True
except ImportError, e:
    UI_ENABLED = False


class BlueAcornInventory(object):

    ###########################################################################
    # Main execution path
    ###########################################################################

    def __init__(self):
        ''' Main execution path '''
        self.db_secret = None
        
         # Read settings, environment variables, and CLI arguments
        self.read_environment()
        self.read_cli_args()
        
        
        # initialize the database
        self.db_engine = None
        self.db_session = None
        self.database_initialize()
        
        # enable encrpytion
        self.enable_encryption()
    
        # initialize UI
        if self.args.edit:
            self.start_ui()
        
        if self.args.add_group:
            group_name = self.args.add_group
            if self.get_group(name=group_name):
                print "Tag Group `%s` already exists!" % (group_name)
                sys.exit(-1)
            self.ui_start('AddGroup',group_name)

        if self.args.add_host:
            host = self.args.add_host
            if self.get_host(host=host):
                print "Host `%s` already exists!" % (host)
                sys.exit(-1)
            self.ui_start('AddHost',host)
            
        if self.args.add_tag:
            tag_name = self.args.add_tag
            if self.get_tag(name=tag_name):
                print "Tag `%s` already exists!" % (tag_name)
                sys.exit(-1)
            self.ui_start('AddTag',tag_name)
            
        if self.args.del_group:
            self.del_group(self.args.del_group)
            print "Group `%s` deleted." % (self.args.del_group)
            sys.exit()
            
        if self.args.del_tag:
            self.del_tag(self.args.del_tag)
            print "Tag `%s` deleted." % (self.args.del_tag)
            sys.exit()
            
        if self.args.del_host:
            self.del_host(self.args.del_host)
            print "Host `%s` deleted." % (self.args.del_host)
            sys.exit()
           
           
           
        # --list or --host requested, output ansible-compliant inventory 
        ################################################################
        
        query = self.database_get_session().query(Host)
        if self.args.host:
            host = query.filter_by(host=self.args.host).first()
            inventory = self.get_host_vars(host) if host else {}
        else:
            inventory = {}
            hostvars = {}
            hostgroups = {}
            for host in query:
                hostvars[host.host] = self.get_host_vars(host)
                hostgroups[host.host] = []
                
                for group in [tag.name for tag in host.tags]:
                    if group not in inventory:
                        inventory[group] = []
                        
                    inventory[group].append(host.host)
                    hostgroups[host.host].append(group)
                
            inventory['_meta'] = {"hostvars": hostvars}
            
        
        if self.args.ssh_config:
            print "##### dbinventory hosts #####"
            print "#############################"
            
            for host, vars in sorted(hostvars.iteritems()):
                print '\n## %s groups: ' % (host) + ', '.join(hostgroups[host])
                print "Host %s" % (host)
                if 'ansible_ssh_host' in vars:
                    print "HostName %s" % (vars['ansible_ssh_host'])
                if 'ansible_ssh_user' in vars:
                    print "User %s" % (vars['ansible_ssh_user'])
                    
                
        elif self.args.pretty:
            print json.dumps(inventory, sort_keys=True, indent=2)
        else:
            print json.dumps(inventory)
        
        
        sys.exit()
        
    def get_host_vars(self, host):
        return transmorg([host.host_name, host.ssh_user, host.ssh_port, host.ssh_pass, host.sudo_pass], ['ansible_ssh_host', 'ansible_ssh_user', 'ansible_ssh_port','ansible_ssh_pass','ansible_sudo_pass'])
        


    ###########################################################################
    # Script configuration
    ###########################################################################

    def read_environment(self):
        ''' Reads the settings from environment variables '''
        # Setup credentials
        if os.getenv("DBINVENTORY_PATH"): self.db_path = os.getenv("DBINVENTORY_PATH")
        if os.getenv("DBINVENTORY_SECRET"): self.db_secret = os.getenv("DBINVENTORY_SECRET")


    def read_cli_args(self):
        ''' Command line argument processing '''
        parser = argparse.ArgumentParser(description='Produce an Ansible Inventory file from an sqlite database')
        
        parser.add_argument('--pretty', '-p', action='store_true', help='Pretty-print results')
        
        
        parser.add_argument('--db-path', action='store', help='Path to Hosts Database File, defaults to DBINVENTORY_PATH environment variable if set, or "<current working directory>/.dbinventory.sqlite3"')
        
        parser.add_argument('--db-create', action='store_true', help='When set, attempt to create the database if it does not already exist')
        parser.add_argument('--db-export', action='store_true', help='Export groups, tags, and hosts as JSON')
        parser.add_argument('--db-import', action='store', help='Pathname to JSON file containing groups, tags, and hosts to import.')
        parser.add_argument('--db-secret', action='store', help='Database Secret Key for host password encryption, defaults to DBINVENTORY_SECRET environment variable')
        
        parser.add_argument('--list', action='store_true', help='List all active Hosts (default: True)')
        parser.add_argument('--host', action='store', help='Get all Ansible inventory variables about a specific Host')

        
        parser.add_argument('--edit','-e', action='store_true', help='Manage Hosts and Tags')
        
        parser.add_argument('--add-group', action='store', help='Add a Tag Group by Name')
        parser.add_argument('--add-host', action='store', help='Add a Host by Name')
        parser.add_argument('--add-tag', action='store', help='Add a Tag by Name')
        
        parser.add_argument('--del-group', action='store', help='Remove a Tag Group by Name')
        parser.add_argument('--del-host', action='store', help='Remove a Host by Name')
        parser.add_argument('--del-tag', action='store', help='Remove a Tag by Name')
        
        parser.add_argument('--ssh-config','-c', action='store_true', help='Output hosts in SSH Config format')
        
        
        self.args = parser.parse_args()

        if self.args.db_path: self.db_path = self.args.db_path
        if self.args.db_secret: self.db_secret = self.args.db_secret


    ###########################################################################
    # Data Management
    ###########################################################################
    
    def database_initialize(self):
        
        if not hasattr(self, 'db_path'):
            self.db_path = os.path.dirname(os.path.abspath(__file__)) + '/.dbinventory.sqlite3'  
            
        if not os.path.isfile(self.db_path):
            if(self.args.db_create):
                self.database_create_tables()
            else:
                print "\nDatabase %s does not exist.\n\nSpecify a location, or use --db-create to start a new database" % (self.db_path)
                sys.exit(-1)
                
        
        if self.args.db_import:
            self.database_import(self.args.db_import)
            print "imported data."
            sys.exit(0)
            
            
        if self.args.db_export:
            print json.dumps(self.database_export())
            sys.exit(0)
            
        return self.database_get_session()
    
    
    def database_create_tables(self):
        engine = self.database_get_engine()
        Base.metadata.create_all(engine)
        
    def database_get_session(self):
        if not self.db_session:
            self.db_session = Session(self.database_get_engine())
            
        return self.db_session
        
    def database_get_engine(self):
        if not self.db_engine:
            self.db_engine = create_engine('sqlite:///' + self.db_path, echo=False)
        
        return self.db_engine 
    
    def database_import(self, filename):
        
        if not os.path.isfile(filename):
            filename = os.path.dirname(os.path.realpath(__file__)) + filename
            if not os.path.isfile(filename):
                print "\nImport File '%s' does not exist." % (filename)
                sys.exit(-1)
        
        with open(filename) as data_file:    
            rows = json.load(data_file)
        
        for key in ['groups', 'tags', 'hosts']:
            if key in rows:
                update_method = getattr(self, "add_or_update_" + key[:-1])
                record_method = getattr(self, "get_" + key[:-1])
                for data in rows[key]:
                    record = record_method(host=data['host']) if key == "hosts" else record_method(name=data['name'])
                    if record:
                        data['id'] = record.id
                    update_method(data)
        
        return
    
    
    def database_export(self):
        
        output = {"groups": [], "tags": [], "hosts": []}
        db = self.database_get_session()
        
        for group in db.query(TagGroup):
            output['groups'].append({"name": group.name, "type": group.selection_type})
            
        for tag in db.query(Tag):
            output['tags'].append({"name": tag.name, "group": tag.group.name})

        for host in db.query(Host):
            tags = []
            for tag in host.tags:
                tags.append(tag.name)
                            
            output['hosts'].append({"host": host.host, "host_name": host.host_name, "ssh_user": host.ssh_user, "ssh_port": host.ssh_port, "tags": tags})
            
        return output 
         
    
    def add_or_update_group(self, data):
        type = data.pop('selection_type',None)
        if not type:
            type = data.pop('type')
            
        data['selection_type'] = type
        return self.add_or_update(TagGroup, data)

    def add_or_update_host(self, data):
        Record = self.add_or_update(Host, data)
            
        if 'tags' in data:
            tags = []
            for tag_name in data['tags']:
                TagRecord = self.get_tag(name=tag_name)
                if TagRecord:
                    tags.append(TagRecord)
                    
            Record.tags = tags
            self.database_get_session().commit()
    
        return Record
    
    def add_or_update_tag(self, data):
        group = self.get_group(name=data['group'][0])
        if not group:
            print "could not add tag `%s`, group `%s` not found" % (data['name'], data['group'])
            sys.exit(-1)
        
        data['group_id'] = group.id
        return self.add_or_update(Tag, data)
    
    def add_or_update(self, ModelClass, data):
        
        db = self.database_get_session()
        id = data.pop('id',None)
        
        if id:
            Record = db.query(ModelClass).filter_by(id=id).first()
        else:
            Record = ModelClass()
            db.add(Record)
            
        # only adds or update columns, not relationships
        mapper = inspect(ModelClass)
        for column in mapper.column_attrs:
            if column.key in data:
                setattr(Record, column.key, data[column.key])
        
        db.commit()
        return Record
    
    def del_group(self, name):
        return self.del_record(self.get_group(name=name))
        
    def del_tag(self, name):
        return self.del_record(self.get_tag(name=name))
    
    def del_host(self, name):
        return self.del_record(self.get_host(host=name))
    
    def del_record(self, record):
        if record:
            db = self.database_get_session()
            db.delete(instance)
            db.commit()
   
    def get_group(self, **kwargs):
        return self.get_record(TagGroup,**kwargs)
    
    def get_host(self, **kwargs):
        return self.get_record(Host,**kwargs)
            
    def get_tag(self, **kwargs):
        return self.get_record(Tag,**kwargs)
    
    def get_record(self, BaseClass, **kwargs):
        return self.database_get_session().query(BaseClass).filter_by(**kwargs).first()
    

    def enable_encryption(self):
        
        if not self.db_secret:
            return False
        
        global CRYPTO_ENABLED
        CRYPTO_ENABLED = True
        
        db = self.database_get_session()
        db_passphrase = db.query(Config).filter_by(name='passphrase').first()
        db_salt = db.query(Config).filter_by(name='passphrase_salt').first()
        
        global AES_KEY
        salt = db_salt.value if db_salt else aes_saltgen()
        AES_KEY = aes_keygen(self.db_secret, salt)
        
        expected_value = 'secret!'
        
        if not db_passphrase:
            encrypted_value = aes_encrypt(expected_value)
            db.add(Config(name='passphrase_salt', value=salt))
            db.add(Config(name='passphrase', value=encrypted_value))
            db.commit()
        
        elif aes_decrypt(db_passphrase.value) != expected_value:
            print "this database is protected with a different passphrase -- please provide the correct one!"
            sys.exit(-1)
            

    
###########################################################################
# User Interface
###########################################################################
        
    def start_ui(self, form_name=None, entity_name=None):
        if not UI_ENABLED:
            print "`npyscreen` library is required by this command"
            sys.exit(-1)
            
        app = UI().start(self)
        

if UI_ENABLED:
    
    class UI(npyscreen.NPSAppManaged):
        def onStart(self):
            self.addForm("MAIN", UI_MainMenu)
            self.addFormClass("HostForm", UI_HostForm)
            self.addFormClass("TagForm", UI_TagForm)
            
            self.record_name = None
            self.crypto_notified = False
        
        def change_form(self, form_id, record_name=None):
            self.record_name = record_name
            self.switchForm(form_id)
            self.resetHistory()
            
            if form_id == "MAIN":
                self.getForm(form_id).refresh_boxes()
            
        def start(self, controller):
            self.controller = controller
            self.db = controller.database_get_session()
            
            return self.run()
        
        
    class UI_MainMenu(npyscreen.TitleForm):
        
        OK_BUTTON_TEXT = 'Exit'
        
        def create(self):
            self.name="ansible-dbinventory  -  l: search L: clear n: next match p: prev match"
            self.boxes = [
              self.add(UI_HostsBox,name="Hosts:", max_width=50, relx=2),
              self.add(UI_TagsBox,name="Tags:", max_width=20, rely=1, relx=52)
            ]
            
            self.refresh_boxes()
            
        def post_edit_loop(self):
            self.parentApp.switchForm(None)
            
        def refresh_boxes(self):
            for box in self.boxes:
                box.refresh_values()
    
    class UI_Box(npyscreen.BoxTitle):
        
        ActionForm = None
        
        def __init__(self, screen, *args, **kwargs):
            widget_args = {"value_changed_callback": self.handle_selection}
            footer = "+ add / - del"
            super(UI_Box, self).__init__(screen, contained_widget_arguments=widget_args, footer=footer, *args, **kwargs)
            self.entry_widget.add_handlers({"-": self.handle_del,"+": self.handle_add})
            
        def get_selection(self, cursor=False):
            widget = self.entry_widget
            position = widget.cursor_line if cursor else widget.value
            
            return widget.values[position] if position != None else None
        
        def handle_selection(self, widget):
            selection = self.get_selection()
            
            if selection:
                self.handle_add(selection=selection)
                
        def handle_add(self, *args, **kwargs):
            selection = kwargs['selection'] if 'selection' in kwargs else None
            self.parent.parentApp.change_form(self.ActionForm, record_name=selection)
            
        def handle_del(self, *args, **kwargs):
            record_name = self.get_selection(cursor=True)
            if npyscreen.notify_yes_no("Really delete %s?" % (record_name)):
                self.delete_record(record_name)
                self.refresh_values()
                
        def refresh_values(self):
            self.entry_widget.value = None
            # TODO: case insensitive sort -- preferable at DBAL
            self.values = [r for r, in sorted(self.get_values_query())]
            self.update()
            
        def delete_record(self):
            pass
        
        def get_values_query(self):
            pass
        
            
    class UI_HostsBox(UI_Box):
        
        ActionForm = 'HostForm'
        
        def delete_record(self, record_name):
            self.parent.parentApp.controller.del_host(record_name)
                
        def get_values_query(self):
            return self.parent.parentApp.db.query(Host.host)
            
    class UI_TagsBox(UI_Box):
        ActionForm = 'TagForm'
        
        def delete_record(self, record_name):
            self.parent.parentApp.controller.del_tag(record_name)
                
        def get_values_query(self):
            return self.parent.parentApp.db.query(Tag.name)
    
    class UI_Form(npyscreen.ActionFormExpandedV2):
        
        OK_BUTTON_TEXT = 'Save (^S)'
        CANCEL_BUTTON_TEXT = 'Cancel (^X)'
        CANCEL_BUTTON_BR_OFFSET = (1, 18)
        
        def __init__(self, *args, **kwargs):
            self.FIELDS = {}
            self.REQUIRED_FIELDS = []
            super(UI_Form,self).__init__(*args, **kwargs)
            
            record = self.get_record()
            if record and record.id:
                self.add_field('id','id',npyscreen.Textfield,value=record.id, editable=False, hidden=True, rely=1)
                
            self.add_handlers({'^X': self.on_cancel,"^S": self.on_ok})
        
        def add_field(self, field_id, prompt, field_class, **kwargs):
            self.FIELDS[field_id] = self.add(field_class, name=prompt, **kwargs)
            return self.FIELDS[field_id]
            
        def add_required_field(self, field_id, prompt, *args, **kwargs):
            self.REQUIRED_FIELDS.append(field_id)
            prompt = prompt + ' *'
            
            field = self.add_field(field_id, prompt, *args, **kwargs)
            field.labelColor = 'STANDOUT'
            
        def on_cancel(self, *args, **kwargs):
            return self.parentApp.change_form('MAIN')
        
        def on_ok(self, *args, **kwargs):
            data = self.get_data_to_add()
            
            for required_key in self.REQUIRED_FIELDS:
                if not data.get(required_key,False):
                    return npyscreen.notify_confirm('Please complete all required fields')
                
            if self.add_record(data):
                return self.parentApp.change_form('MAIN')
                
            npyscreen.notify_confirm('Error Adding!')
                
        def get_data_to_add(self):
            
            data = {}
            
            for key, field in self.FIELDS.iteritems():
                if isinstance(field,npyscreen.TitleSelectOne) or isinstance(field, npyscreen.SelectOne):
                    try:
                        value = field.get_selected_objects()
                    except:
                        value = None
                        
                elif isinstance(field,npyscreen.TitleMultiSelect) or isinstance(field, npyscreen.MultiSelect):
                    value = field.get_selected_objects()
                    
                else:
                    value = field.value
                    
                data[key] = value
                    
            return data
        
        def add_record(self, data):
            pass
        
        def get_record(self):
            pass
                
            
            
    class UI_AddGroupForm(UI_Form):
        
        def create(self):
            super(self.__class__,self).create()
            
            enums = TagGroup.selection_type.property.columns[0].type.enums
            self.add_required_field('type','Type:',npyscreen.TitleSelectOne,values=enums)
            
            
        def add_record(self,data):
            if self.parentApp.controller.add_or_update_group(data):
                npyscreen.notify_confirm("Added Tag Group `%s`" % (data['name']))
                return True
                
            return False
            
            
    class UI_TagForm(UI_Form):
        
        def create(self):
            record = self.get_record()
            self.name = 'Edit Tag' if record.id else 'Add Tag'
            self.add_required_field('name', 'Tag:', npyscreen.TitleText, value=record.name)
            
            groups = self.parentApp.db.query(TagGroup)
            group_names = [group.name for group in groups]
            group_ids = [group.id for group in groups]
            

            value = []
            for idx, group_id in enumerate(group_ids):
                if group_id == record.group_id:
                    value.append(idx)
            
            height = min(10, len(group_ids)) + 2
            self.add_required_field('group','Group:',npyscreen.TitleSelectOne,values=group_names,value=value,max_height=height)


        
        def add_record(self,data):
            if self.parentApp.controller.add_or_update_tag(data):
                return True
        
        def get_record(self):
            if (self.parentApp.record_name):
                return self.parentApp.controller.get_tag(name=self.parentApp.record_name)
            
            return Tag()
        
            
    class UI_HostForm(UI_Form):
        
        def create(self):
            record = self.get_record()
            self.name = 'Edit Host' if record.id else 'Add Host'
            
            self.add_required_field('host', 'Host:', npyscreen.TitleText, value=record.host)
            self.add_field('host_name','Host IP/FQDN:', npyscreen.TitleText, value=record.host_name)
            self.add_required_field('ssh_user','SSH User:', npyscreen.TitleText, value=record.ssh_user)
            self.add_field('ssh_port','SSH Port:', npyscreen.TitleText, value=str(record.ssh_port))
            
            
            global CRYPTO_ENABLED
            if not CRYPTO_ENABLED and not self.parentApp.crypto_notified:
                self.parentApp.crypto_notified = True
                npyscreen.notify_confirm('Provide a --db-secret if you want to set the ssh_pass and sudo_pass variables.')
            
            self.add_field('ssh_pass','SSH Pass:', npyscreen.TitleText, editable=(CRYPTO_ENABLED), value=record.ssh_pass)
            self.add_field('sudo_pass','sudo Pass:', npyscreen.TitleText, editable=(CRYPTO_ENABLED), value=record.sudo_pass)
           
            
            db = self.parentApp.db
            host_tags = [tag.name for tag in record.tags] if record.id else []
            
            #for group in db.query(TagGroup).filter(TagGroup.selection_type.in_(['select','multiselect'])):
            for group in db.query(TagGroup):
                tags = [tag.name for tag in group.tags]
                prompt = group.name + ':'
                height = min(10, len(tags)) + 2
                
                value = []
                for idx, tag in enumerate(tags):
                    if tag in host_tags:
                        value.append(idx)
                
                if group.selection_type == 'select':
                    value = value[0] if len(value) else None
                    self.add_field('_tag_group_' + group.name, group.name + ':', npyscreen.TitleSelectOne, values=tags, value=value, max_height=height)
                else:
                    self.add_field('_tag_group_' + group.name, group.name + ':', npyscreen.TitleMultiSelect, values=tags, value=value, max_height=height)
                
                
        def add_record(self,data):
            
            new_data = {"tags": []}
            tag_prefix = '_tag_group_'
            
            for key, value in data.iteritems():
                if (value):
                    if key.startswith(tag_prefix):
                        new_data['tags'] += value
                    else:
                        new_data[key] = value
            
            if self.parentApp.controller.add_or_update_host(new_data):
                return True
            
        def get_record(self):
            if (self.parentApp.record_name):
                return self.parentApp.controller.get_host(host=self.parentApp.record_name)
            
            return Host()
                


###########################################################################
# Utility
###########################################################################
def aes_encrypt(data):
    if CRYPTO_ENABLED and data:
        cipher = AES.new(AES_KEY)
        data = data + (" " * (16 - (len(data) % 16)))
        return binascii.hexlify(cipher.encrypt(data))

def aes_decrypt(data):
    if CRYPTO_ENABLED and data:
        cipher = AES.new(AES_KEY)
        return cipher.decrypt(binascii.unhexlify(data)).rstrip()
    
def aes_keygen(passphrase=None, salt=None):
    if not passphrase or not salt: 
        return None

    return hashlib.sha256(binascii.unhexlify(salt) + passphrase).digest()
    
    
def aes_saltgen():
    return binascii.hexlify(get_random_bytes(16))
    
    
def transmorg(data, keys):
    
    output = {}
    values = [value for value in data]
    
    for i, value in enumerate(values):
        if (value):
            output[keys[i]] = value
            
    return output
    
            
###########################################################################
# SQLAlachemy Models
###########################################################################

#@TODO - cascade deletions

Base = declarative_base()

class EncryptedValue(TypeDecorator):
    impl = String

    def process_bind_param(self, value, dialect):
        return aes_encrypt(value)

    def process_result_value(self, value, dialect):
        return aes_decrypt(value)
    

class Host(Base):
    __tablename__ = 'host'
    
    id = Column(Integer, primary_key=True)
    tags = relationship('Tag', secondary='host_tag_map', backref="hosts")
    
    host = Column(String)
    host_name = Column(String)
    ssh_user = Column(String)
    ssh_port = Column(Integer)
    ssh_pass = Column("encrypted_ssh_pass", EncryptedValue(40), nullable=True)
    sudo_pass = Column("encrypted_sudo_pass", EncryptedValue(40), nullable=True)
    
    __mapper_args__ = {"order_by": host}
    
    
class Tag(Base):
    __tablename__ = 'tag'
    
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('tag_group.id'))
    
    name = Column(String)
    
    __mapper_args__ = {"order_by": name}
    
class TagGroup(Base):
    __tablename__ = 'tag_group'
    
    id = Column(Integer, primary_key=True)
    tags = relationship("Tag", backref="group")
    
    name = Column(String)
    selection_type = Column(Enum('select', 'multiselect', name='tag_group_types'))
    
    __mapper_args__ = {"order_by": name}
    
     
class HostTagMap(Base):
    __tablename__ = 'host_tag_map'
    
    host_id = Column(Integer, ForeignKey('host.id'), primary_key=True)
    tag_id = Column(Integer, ForeignKey('tag.id'), primary_key=True)
    
    
class Config(Base):
    __tablename__ = 'config'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    value = Column(String(80))
    


    
# Run the script
BlueAcornInventory()

