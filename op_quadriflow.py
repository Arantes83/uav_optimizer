import bpy
from bpy.types import Operator

class UAV_OT_quadriflow(Operator):
    bl_idname = "uav.quadriflow_retopo"
    bl_label = "Run QuadriFlow"
    
    # --- O TOOLTIP DO BOT-O FICA AQUI ---
    bl_description = "Executes native QuadriFlow to generate an all-quad mesh inside a new collection. Ideal for organic terrain"
    
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        # S- permite clicar no bot-o se houver pelo menos uma malha selecionada
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props = context.scene.uav_props
        target_quads = props.target_quad_count
        
        objects_to_process = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not objects_to_process:
            self.report({'WARNING'}, "No valid meshes selected.")
            return {'CANCELLED'}
            
        # ==================================================================
        # 1. CRIAR A NOVA COLE--O PARA O QUADRIFLOW
        # ==================================================================
        base_name = objects_to_process[0].name.replace("_QEM", "")
        qflow_col_name = f"{base_name}_QuadriFlow"
        
        if qflow_col_name not in bpy.data.collections:
            qflow_col = bpy.data.collections.new(qflow_col_name)
            context.scene.collection.children.link(qflow_col)
        else:
            qflow_col = bpy.data.collections[qflow_col_name]
            
        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        created_objects = []

        self.report({'INFO'}, f"Starting QuadriFlow (Target: {target_quads} quads). Blender may freeze for a moment...")

        # ==================================================================
        # 2. PROCESSAR CADA CHUNK SELECIONADO
        # ==================================================================
        for obj in objects_to_process:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            
            bpy.ops.object.duplicate()
            new_obj = context.active_object
            
            clean_name = obj.name.replace("_QEM", "")
            new_obj.name = f"{clean_name}_QuadriFlow"
            
            obj.hide_set(True)
            obj.select_set(False)
            
            for coll in new_obj.users_collection:
                coll.objects.unlink(new_obj)
            qflow_col.objects.link(new_obj)
            
            # ==================================================================
            # 3. EXECU--O DO QUADRIFLOW (Corrigido para o Blender 4.4)
            # ==================================================================
            try:
                # Removemos o 'preserve_paint_mask' que estava a causar o erro na vers-o 4.4
                bpy.ops.object.quadriflow_remesh(
                    mode='FACES',
                    target_faces=target_quads,
                    use_mesh_symmetry=False,
                    use_preserve_sharp=True,
                    use_preserve_boundary=True,
                    smooth_normals=True
                )
                
                created_objects.append(context.active_object)
                
            except RuntimeError as e:
                self.report({'ERROR'}, f"QuadriFlow failed on {new_obj.name}. Check console.")
                print(f"QuadriFlow Error: {e}")
                bpy.data.objects.remove(new_obj, do_unlink=True)

        # ==================================================================
        # 4. LIMPEZA FINAL E SELE--O
        # ==================================================================
        bpy.ops.object.select_all(action='DESELECT')
        for created_obj in created_objects:
            if created_obj:
                created_obj.select_set(True)
                
        if created_objects:
            context.view_layer.objects.active = created_objects[0]
            self.report({'INFO'}, f"QuadriFlow Completed Successfully! Generated {len(created_objects)} quad meshes in '{qflow_col_name}'.")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "QuadriFlow failed to generate any meshes.")
            return {'CANCELLED'}