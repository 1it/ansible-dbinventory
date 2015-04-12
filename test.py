#!/usr/bin/env python
import npyscreen, curses
import hashlib

import logging
logging.basicConfig(filename='test.log',level=logging.DEBUG)



class UI(npyscreen.NPSAppManaged):
    def onStart(self):
        self.addForm("MAIN", UI_MainMenu)
        self.addFormClass("HostForm", UI_HostForm)
        self.addFormClass("TagForm", UI_HostForm)
        
        
    def onCleanExit(self):
        npyscreen.notify_wait("Goodbye!")
    
    def change_form(self, name):
        # Switch forms.  NB. Do *not* call the .edit() method directly (which 
        # would lead to a memory leak and ultimately a recursion error).
        # Instead, use the method .switchForm to change forms.
        self.switchForm(name)
        
        # By default the application keeps track of every form visited.
        # There's no harm in this, but we don't need it so:        
        self.resetHistory()
    
    
class UI_MainMenu(npyscreen.TitleForm):
    
    OK_BUTTON_TEXT = 'Exit'
    
    def create(self):
        self.name="ansible-dbinventory  -  l: search L: clear n: next match p: prev match"
        
        hosts = self.add(UI_HostsBox,name="Hosts:", max_width=50, relx=2)
        tags = self.add(UI_TagsBox,name="Tags:", max_width=20, rely=1, relx=52)
        

class UI_Box(npyscreen.BoxTitle):
    
    def __init__(self, screen, *args, **kwargs):
        
        widget_args = {"value_changed_callback": self.handle_selection}
        footer = "+ add / - del"
        super(UI_Box, self).__init__(screen, contained_widget_arguments=widget_args, footer=footer, *args, **kwargs)
        
        self.entry_widget.add_handlers({"-": self.handle_del,"+": self.handle_add})
        self.selection = None
        
    def get_selected_value(self):
        if self.entry_widget.value:
            return self.entry_widget.values[self.entry_widget.value]
        
    def handle_selection(self, widget):
        self.selection = self.get_selected_value()
        if self.selection:
            return self.handle_add()
            
    def handle_add(self, *args, **kwargs):
        pass
    
    def handle_del(self, *args, **kwargs):
        pass
        
        
        
class UI_HostsBox(UI_Box):
    
    def edit(self):
        
        md5s = ['xxxxxx.dgfjdfjdfhjdsfa.xccxnnaqsdnbabsd-dscfjsdj.com']
        md5s += [hashlib.md5().hexdigest() for i in range(33)]
        self.values = md5s
        
        logging.info('EDIT called')
        
        return super(UI_HostsBox,self).edit()
    
    def handle_add_entity(self, *args, **kwargs):
        npyscreen.notify_confirm("ADD %s %s %s" % (self.name, self.get_action_form(), kwargs))
        self.parent.parentApp.change_form(self.get_action_form())
    
        
    def handle_del_entity(self, *args, **kwargs):
        npyscreen.notify_confirm("DEL %s %s" % (self.name, pprint(args), kwargs))
        
        
        
class UI_TagsBox(UI_Box):
    
    def handle_add(self, *args, **kwargs):
        npyscreen.notify_confirm("ADD %s %s %s" % (self.name, self.get_action_form(), kwargs))
        self.parent.parentApp.change_form(self.get_action_form())
    
        
    def handle_del(self, *args, **kwargs):
        npyscreen.notify_confirm("DEL %s %s %s" % (self.name, self.get_action_form(), kwargs))
        
            

    
class UI_HostForm(npyscreen.ActionFormMinimal):
    pass
    


def main():
    TA = UI()
    TA.run()


if __name__ == '__main__':
    main()



