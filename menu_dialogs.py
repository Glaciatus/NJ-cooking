"""Modal, previewable manual replacements and moves. No random automatic replacement."""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from core import recipe_key,day_duplicates
from nutrition import recipe_nutrition,nutrition_text,normalize
from estimation import servings_info
from tagging import recipe_tags
from menu_editing import TIMES,replace_dish,swap_dishes,move_dish

class ReplaceDialog(tk.Toplevel):
    def __init__(self,app,source):
        super().__init__(app);self.app=app;self.source=source;self.timer=None;self.page=0
        self.title('Заменить блюдо в меню');self.transient(app)
        self.geometry('980x700');self.minsize(800,560)
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        footer=ttk.Frame(self,padding=10);footer.pack(side='bottom',fill='x')
        ttk.Button(footer,text='Отмена',command=self.destroy).pack(side='right')
        self.apply_button=ttk.Button(footer,text='Заменить и пересчитать',command=self.apply,state='disabled')
        self.apply_button.pack(side='right',padx=10)
        top=ttk.Frame(self,padding=10);top.pack(fill='x')
        ttk.Label(top,text=f'День {source[0]+1} · {TIMES[source[1]]} · вместо «{app.week[source[0]][source[1]].name}»',wraplength=900).pack(anchor='w')
        self.db_labels={d.name+' ['+d.uid[:8]+']':d.uid for d in app.manager.databases if d.enabled}
        current=app.week[source[0]][source[1]].database_id
        initial=next((label for label,uid in self.db_labels.items() if uid==current),next(iter(self.db_labels),''))
        self.database=tk.StringVar(value=initial)
        db=ttk.Combobox(top,textvariable=self.database,values=list(self.db_labels),state='readonly',width=40)
        db.pack(anchor='w',pady=6);db.bind('<<ComboboxSelected>>',lambda _:self.search())
        self.query=tk.StringVar()
        ttk.Label(top,text='Поиск по названию в выбранной включённой базе').pack(anchor='w')
        ttk.Entry(top,textvariable=self.query).pack(fill='x')
        self.query.trace_add('write',lambda *_:self.schedule())
        self.preview=ScrolledText(self,height=9,wrap='word',state='disabled',padx=8,pady=8)
        self.preview.pack(side='bottom',fill='x',padx=10,pady=5)
        pages=ttk.Frame(self,padding=(10,4));pages.pack(side='bottom',fill='x')
        ttk.Button(pages,text='← Назад',command=lambda:self.turn(-1)).pack(side='left')
        ttk.Button(pages,text='Далее →',command=lambda:self.turn(1)).pack(side='left',padx=5)
        self.count=ttk.Label(pages);self.count.pack(side='left')
        area=ttk.Frame(self,padding=10);area.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(area,columns=('meal',),show='tree headings',height=8,selectmode='browse')
        self.tree.heading('#0',text='Рецепт');self.tree.heading('meal',text='В карточке')
        self.tree.column('#0',width=680);self.tree.column('meal',width=130)
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.tree.yview);scroll.pack(side='right',fill='y')
        self.tree.configure(yscrollcommand=scroll.set);self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',lambda _:self.show_preview())
        self.search();self.grab_set()

    def schedule(self):
        if self.timer:self.after_cancel(self.timer)
        self.timer=self.after(200,self.search)
    def turn(self,delta):self.page=max(0,self.page+delta);self.search(reset=False)
    def search(self,reset=True):
        if self.timer:self.after_cancel(self.timer);self.timer=None
        if reset:self.page=0
        dbid=self.db_labels.get(self.database.get())
        self.matches=[r for r in self.app.manager.get(dbid).recipes if normalize(self.query.get()) in normalize(r.name)] if dbid else []
        self.page=min(self.page,max(0,(len(self.matches)-1)//100))
        self.tree.delete(*self.tree.get_children())
        self.lookup={recipe_key(r):r for r in self.matches}
        for r in self.matches[self.page*100:(self.page+1)*100]:self.tree.insert('','end',iid=recipe_key(r),text=r.name,values=(r.meal,))
        self.count.config(text=f'Найдено: {len(self.matches)} · Страница {self.page+1}')
        self.apply_button.config(state='disabled')
        self.text('Выберите рецепт. После замены автоматически обновятся КБЖУ и покупки. Нарушения прежних условий будут показаны как предупреждения.')
        if not self.db_labels:self.text('Нет включённых баз. Включите нужную базу на шаге 1, затем повторите замену.')
    def text(self,value):
        self.preview.config(state='normal');self.preview.delete('1.0','end');self.preview.insert('1.0',value);self.preview.config(state='disabled')
    def selected(self):
        keys=self.tree.selection();return self.lookup.get(keys[0]) if keys else None
    def show_preview(self):
        r=self.selected()
        if not r:return
        candidate=replace_dish(self.app.week,self.source,r)
        issues=self.app.menu_change_warnings(candidate)
        values,estimated=recipe_nutrition(r)
        self.text(r.name+'\n'+('≈ ' if estimated else '')+nutrition_text(values)+' на одну порцию\n'+servings_info(r).explanation+'\nТеги: '+', '.join(recipe_tags(r))+'\n\n'+('Предупреждения после замены:\n'+'\n'.join(issues) if issues else 'Известных нарушений условий нет.'))
        self.apply_button.config(state='disabled' if any(day_duplicates(day) for day in candidate) else 'normal')
    def apply(self):
        r=self.selected()
        if r and self.app.apply_menu_change(replace_dish(self.app.week,self.source,r),'Замена блюда',self.source):self.destroy()
    def destroy(self):
        if self.timer:self.after_cancel(self.timer)
        super().destroy()

class MoveDialog(tk.Toplevel):
    def __init__(self,app,source):
        super().__init__(app);self.app=app;self.source=source
        self.title('Перенести или обменять блюдо');self.transient(app);self.geometry('820x560')
        self.day=tk.StringVar(value=f'День {source[0]+1}');self.meal=tk.StringVar(value=TIMES[source[1]])
        self.mode=tk.StringVar(value='swap')
        footer=ttk.Frame(self,padding=10);footer.pack(side='bottom',fill='x')
        ttk.Button(footer,text='Отмена',command=self.destroy).pack(side='right')
        self.apply_button=ttk.Button(footer,text='Применить и пересчитать',command=self.apply)
        self.apply_button.pack(side='right',padx=10)
        frame=ttk.Frame(self,padding=12);frame.pack(fill='x')
        ttk.Label(frame,text=f'Откуда: день {source[0]+1}, {TIMES[source[1]]} · {app.week[source[0]][source[1]].name}',wraplength=760).pack(anchor='w')
        ttk.Label(frame,text='Куда:').pack(anchor='w',pady=(8,0))
        ttk.Combobox(frame,textvariable=self.day,values=[f'День {n}' for n in range(1,8)],state='readonly').pack(anchor='w',pady=5)
        ttk.Combobox(frame,textvariable=self.meal,values=TIMES,state='readonly',width=30).pack(anchor='w')
        ttk.Radiobutton(frame,text='Обменять местами — изменятся только две позиции',variable=self.mode,value='swap').pack(anchor='w',pady=(10,0))
        ttk.Radiobutton(frame,text='Перенести со сдвигом — промежуточные блюда сдвинутся на одну позицию',variable=self.mode,value='move').pack(anchor='w')
        self.preview=ScrolledText(self,wrap='word',height=8,state='disabled',padx=10,pady=10);self.preview.pack(fill='both',expand=True,padx=12)
        for var in (self.day,self.meal,self.mode):var.trace_add('write',lambda *_:self.show_preview())
        self.show_preview();self.grab_set()
    def target(self):return (int(self.day.get().split()[-1])-1,TIMES.index(self.meal.get()))
    def candidate(self):return (swap_dishes if self.mode.get()=='swap' else move_dish)(self.app.week,self.source,self.target())
    def show_preview(self):
        target=self.target();r=self.app.week[target[0]][target[1]]
        candidate=self.candidate()
        issues=self.app.menu_change_warnings(candidate)
        self.apply_button.config(state='disabled' if any(day_duplicates(day) for day in candidate) else 'normal')
        value=f'В выбранной позиции сейчас: «{r.name}».\nВсе 21 блюдо сохраняются.\n\n'+('Предупреждения после изменения:\n'+'\n'.join(issues) if issues else 'Известных нарушений условий нет.')
        self.preview.config(state='normal');self.preview.delete('1.0','end');self.preview.insert('1.0',value);self.preview.config(state='disabled')
    def apply(self):
        action='Обмен блюд' if self.mode.get()=='swap' else 'Перенос со сдвигом'
        if self.app.apply_menu_change(self.candidate(),action,self.target()):self.destroy()
