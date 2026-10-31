"""Local palette on the source-sized hull/barrel; no simulation work."""
from math import cos, radians, sin


def draw_tank(pyxel, tank, *, origin, scale):
    angle = radians(tank['heading_deg']+90)
    c,s = cos(angle),sin(angle)
    factor = tank['display_scale']*scale
    x,y = origin[0]+tank['x']*scale,origin[1]+tank['y']*scale

    def box(left,top,right,bottom,color):
        points = [(x+factor*(lx*c-ly*s),y+factor*(lx*s+ly*c))
                  for lx,ly in ((left,top),(right,top),(right,bottom),(left,bottom))]
        for a,b,d in ((points[0],points[1],points[2]),(points[0],points[2],points[3])):
            pyxel.tri(*a,*b,*d,color)

    box(-30.5,-40.5,30.5,40.5,1)
    box(-22,-38,22,38,3)
    box(-8.5,-55,8.5,0,1)
    box(-6,-53,6,-15,3)
    pyxel.circ(x,y,22.5*factor,1)
    pyxel.circ(x,y,17*factor,3)
