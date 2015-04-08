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
encryption and can only be retrieved by providing the correct passphrase. 

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
    from sqlalchemy import create_engine, Column, Integer, String, Enum, ForeignKey
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import Session
except ImportError, e:
    print "failed=True msg='`sqlalchemy` library required for this script'"
    sys.exit(1)

try:
    from Crypto.Cipher import AES
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

        # BlueAcornInventory data
        self.data = {}  # All DigitalOcean data
        self.inventory = {}  # Ansible Inventory
        self.index = {}  # Various indices of Droplet metadata
        
         # Read settings, environment variables, and CLI arguments
        self.read_environment()
        self.read_cli_args()
        
        
        # initialize the database
        self.db_engine = None
        self.db_session = None
        self.database_initialize()
        
        # initialize UI
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
           
        
        sys.exit()


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
        
        
        parser.add_argument('--db-path', '-d', action='store', help='Path to Hosts Database File, defaults to DBINVENTORY_PATH environment variable if set, or "<current working directory>/hosts.sqlite3"')
        
        parser.add_argument('--db-create', '-c', action='store_true', help='When set, attempt to create the database if it does not already exist')
        parser.add_argument('--db-export', '-e', action='store_true', help='Export groups, tags, and hosts as JSON')
        parser.add_argument('--db-import', '-i', action='store', help='Pathname to JSON file containing groups, tags, and hosts to import.')
        parser.add_argument('--db-secret', '-s', action='store', help='Database Secret Key for host password encryption, defaults to DBINVENTORY_SECRET environment variable')
        
        parser.add_argument('--list', action='store_true', help='List all active Hosts (default: True)')
        parser.add_argument('--host', action='store', help='Get all Ansible inventory variables about a specific Host')


        parser.add_argument('--add-group', action='store', help='Add a Tag Group by Name')
        parser.add_argument('--add-host', action='store', help='Add a Host by Name')
        parser.add_argument('--add-tag', action='store', help='Add a Tag by Name')
        
        parser.add_argument('--del-group', action='store', help='Remove a Tag Group by Name')
        parser.add_argument('--del-host', action='store', help='Remove a Host by Name')
        parser.add_argument('--del-tag', action='store', help='Remove a Tag by Name')
        
        
        
       
        self.args = parser.parse_args()

        if self.args.db_path: self.db_path = self.args.db_path
        if self.args.db_secret: self.db_secret = self.args.db_secret


    ###########################################################################
    # Data Management
    ###########################################################################
    
    def database_initialize(self):
        
        if not hasattr(self, 'db_path'):
            self.db_path = os.path.dirname(os.path.realpath(__file__)) + '/hosts.sqlite3'  
            
        if not os.path.isfile(self.db_path):
            if(self.args.db_create):
                self.database_create_tables()
            else:
                print "\nDatabase %s does not exist.\n\nSpecify a location, or use --db-create to start a new database" % (self.db_path)
                sys.exit(-1)
                
        
        if self.args.db_import:
            self.database_import(self.args.db_import)
            
            
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
            data = json.load(data_file)
            
        
        for key in ['groups', 'tags', 'hosts']:
            if key in data:
                method = getattr(self, "add_" + key[:-1])
                for obj in data[key]:
                    method(obj)
        
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
         
    
    def add_group(self, obj):
        Record = self.get_group(name=obj['name'])
        
        if not Record:
            db = self.database_get_session()
            Record = TagGroup(name=obj['name'], selection_type=obj['type'])
            db.add(Record)
            db.commit()
    
        return Record
    
    def add_host(self, obj):
        Record = self.get_host(host=obj['host'])
        
        if not Record:
            db = self.database_get_session()
            Record = Host(host=obj['host'])
            
            for key in ['host_name', 'ssh_user', 'ssh_port']:
                if key in obj:
                    setattr(Record, key, obj[key])
            
            db.add(Record)
            db.commit()
            
        if 'tags' in obj:
            db = self.database_get_session()
            for tag_name in obj['tags']:
                TagRecord = self.get_tag(name=tag_name)
                if TagRecord:
                    Record.tags.append(TagRecord)
            db.commit()
    
        return Record
    
    def add_tag(self, obj):
        Record = self.get_tag(name=obj['name'])
        group = self.get_group(name=obj['group'])
        
        if not group:
            print "could not add tag `%s`, group `%s` not found" % (obj['name'], obj['group'])
            sys.exit(-1)
        
        
        if not Record:
            db = self.database_get_session()
            Record = Tag(name=obj['name'], group_id=group.id)
            db.add(Record)
            db.commit()
            
        return Record
    
   
    def get_group(self, **kwargs):
        return self.database_get_session().query(TagGroup).filter_by(**kwargs).first()
    
    def get_host(self, **kwargs):
        return self.database_get_session().query(Host).filter_by(**kwargs).first()
            
    def get_tag(self, **kwargs):
        return self.database_get_session().query(Tag).filter_by(**kwargs).first()
    
    
        
        
###########################################################################
# User Interface
###########################################################################

    def ui_start(self, form_name, entity_name=None):
        if not UI_ENABLED:
            print "`npyscreen` library is required by this command"
            sys.exit(-1)
            
        app = UI().start(self, form_name,entity_name)
        

if UI_ENABLED:
    
    class UI(npyscreen.NPSAppManaged):
        def onStart(self):
            self.addForm('AddGroup',UI_AddGroupForm, name="Add Tag Group")
            self.addForm('AddHost',UI_AddHostForm, name="Add Host",minimum_lines=30)
            self.addForm('AddTag',UI_AddTagForm, name="Add Tag",minimum_lines=30)
            
        
        def start(self, controller, start_form, entity_name):
            
            self.controller = controller
            self.db = controller.database_get_session()
            
            self.setNextForm(start_form)
            self.STARTING_FORM = start_form
            self.entity_name = entity_name
            
            return self.run()
            
            
    
    class UI_Form(npyscreen.ActionFormMinimal):
        
        def __init__(self, *args, **kwargs):
            self.FIELDS = {}
            self.REQUIRED_FIELDS = []
            super(UI_Form,self).__init__(*args, **kwargs)
        
        def create(self):
            self.add_required_field('name', 'Name:', npyscreen.TitleText, value=self.parentApp.entity_name, editable=False)
        
        def add_field(self, field_id, prompt, field_class, **kwargs):
            field = self.add(field_class, name=prompt, **kwargs)
            self.FIELDS[field_id] = field
            return field
            
        def add_required_field(self, field_id, prompt, *args, **kwargs):
            self.REQUIRED_FIELDS.append(field_id)
            prompt = prompt + ' *'
            
            field = self.add_field(field_id, prompt, *args, **kwargs)
            field.labelColor = 'STANDOUT'
        
        def on_ok(self):
            obj = self.get_object_to_add()
            
            for required_key in self.REQUIRED_FIELDS:
                if not obj.get(required_key,False):
                    npyscreen.notify_confirm('Please complete all required fields')
                    return
                
            if self.add_object(obj):
                self.parentApp.setNextForm(None)
                return
                
            npyscreen.notify_confirm('Error Adding!')
                
            
        def get_object_to_add(self):
            
            obj = {}
            
            for key, field in self.FIELDS.iteritems():
                if isinstance(field,npyscreen.TitleSelectOne) or isinstance(field, npyscreen.SelectOne):
                    try:
                        value = field.get_selected_objects()[0]
                    except:
                        value = None
                
                elif isinstance(field,npyscreen.TitleMultiSelect) or isinstance(field, npyscreen.MultiSelect):
                    value = field.get_selected_objects()
                
                else:
                    value = field.value
                    
                obj[key] = value
                    
                    
            return obj
        
        def add_object(self, obj):
            pass
                
            
            
    class UI_AddGroupForm(UI_Form):
        
        def create(self):
            super(self.__class__,self).create()
            
            enums = TagGroup.selection_type.property.columns[0].type.enums
            self.add_required_field('type','Type:',npyscreen.TitleSelectOne,values=enums)
            
            
        def add_object(self,obj):
            if self.parentApp.controller.add_group(obj):
                npyscreen.notify_confirm("Added Tag Group `%s`" % (obj['name']))
                return True
                
            return False
            
            
    class UI_AddTagForm(UI_Form):
        
        def create(self):
            super(self.__class__,self).create()
            
            groups = [group.name for group in self.parentApp.db.query(TagGroup)]
            height = min(10, len(groups)) + 1
            
            self.add_required_field('group','Group:',npyscreen.TitleSelectOne,values=groups,max_height=height)
            
        
        def add_object(self,obj):
            if self.parentApp.controller.add_tag(obj):
                npyscreen.notify_confirm("Added Tag `%s`" % (obj['name']))
                return True
                
            return False
        
            
    class UI_AddHostForm(UI_Form):
        def create(self):
            
            self.add_required_field('host', 'Host:', npyscreen.TitleText, value=self.parentApp.entity_name, editable=False)
            self.add_field('host_name','Host IP/FQDN:', npyscreen.TitleText)
            self.add_field('ssh_user','SSH User:', npyscreen.TitleText)
            self.add_field('ssh_port','SSH Port:', npyscreen.TitleText)
            
            
            for group in self.parentApp.db.query(TagGroup):
                tags = [tag.name for tag in group.tags]
                prompt = group.name + ':'
                height = min(10, len(tags)) + 1 
                
                if group.selection_type == 'select':
                    self.add_field(group.name, group.name + ':', npyscreen.TitleSelectOne, values=tags,max_height=height)
                
                elif group.selection_type == 'multiselect':
                    self.add_field(group.name, group.name + ':', npyscreen.TitleSelectOne, values=tags,max_height=height)
                    
                elif group.selection_type == 'checkbox':
                    for tag_name in tags:
                        self.add(npyscreen.CheckBox,value=False,name=tag_name)
                        
        def on_ok(self):
            type = self.widget_group.get_selected_objects()
            
            if type:
                obj = {"name": self.parentApp.entity_name,"type": type[0]}
                # @TODO error handling for failed object creation
                self.parentApp.controller.add_group(obj)
                npyscreen.notify_confirm("Added tag `%s`" % (self.parentApp.entity_name))
                self.KEEP_EDITING = False
            else:
                npyscreen.notify_confirm('Please select a Tag Group Selection Type')
                        

            
###########################################################################
# SQLAlachemy Models
###########################################################################

Base = declarative_base()

class Host(Base):
    __tablename__ = 'host'
    
    id = Column(Integer, primary_key=True)
    tags = relationship('Tag', secondary='host_tag_map')
    
    host = Column(String)
    host_name = Column(String)
    ssh_user = Column(String)
    ssh_port = Column(Integer)
    
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
    selection_type = Column(Enum('checkbox', 'select', 'multiselect', name='tag_group_types'))
    
    __mapper_args__ = {"order_by": name}
    
     
class HostTagMap(Base):
    __tablename__ = 'host_tag_map'
    
    host_id = Column(Integer, ForeignKey('host.id'), primary_key=True)
    tag_id = Column(Integer, ForeignKey('tag.id'), primary_key=True)
    

# Run the script
BlueAcornInventory()
