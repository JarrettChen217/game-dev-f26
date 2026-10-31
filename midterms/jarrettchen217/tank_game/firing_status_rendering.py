"""A bounded public status card shared by inspection and lesson five."""
from tank_game.firing_status import FiringStatus
from tank_game.ui_rendering import label


def bullet_row_capacity(bounds: tuple[int,int,int,int], *, scale: int = 1) -> int:
    return max(0,(bounds[3]-4)//(8*scale+2)-5)


def _seconds(value):
    return f'{max(.01,value) if value>0 else 0:.2f} s'


def draw_firing_status(pyxel, status: FiringStatus, *, bounds: tuple[int,int,int,int],
                       offset: int = 0, scale: int = 1) -> int:
    x,y,width,height=bounds
    capacity=bullet_row_capacity(bounds,scale=scale)
    if width<16 or height<8*scale+4:
        return capacity
    pyxel.rect(x,y,width,height,7)
    pyxel.rectb(x,y,width,height,5)
    x+=2
    y+=2
    width-=4
    line_height=8*scale+2
    bottom=bounds[1]+height-2
    chars=width//(4*scale)

    def text(value,ty,color=0,max_chars=chars):
        if ty+8*scale<=bottom:
            value=value if len(value)<=max_chars else value[:max(0,max_chars-3)]+'...'
            label(pyxel,x,ty,value[:max_chars],color,scale=scale)

    text(f'Can fire: {"Yes" if status.can_fire else "No"} | Cooldown: '
         f'{_seconds(status.cooldown_remaining)}',y)
    text(f'In flight: {status.active_bullets}/{status.capacity} | '
         f'Free slots: {status.free_slots}/{status.capacity}',y+line_height)
    text('; '.join(status.reasons),y+2*line_height,3 if status.can_fire else 0)
    text('BULLET LIFETIME',y+3*line_height)
    offset=max(0,min(offset,max(0,len(status.bullets)-capacity)))
    rows=status.bullets[offset:offset+capacity]
    timer_width=12*4*scale
    id_width=min(width//4,12*4*scale)
    bar_x=x+id_width+2
    bar_width=max(0,width-id_width-timer_width-6)
    for i,bullet in enumerate(rows):
        row_y=y+(4+i)*line_height
        if row_y+8*scale>bottom:
            break
        identity='#'+bullet.id[7:] if bullet.id.startswith('bullet-') else bullet.id
        text(identity+' ',row_y,max_chars=max(1,id_width//(4*scale)))
        if bar_width:
            pyxel.rect(bar_x,row_y+2*scale,bar_width,4,5)
            filled=min(bar_width,max(1,round(bar_width*bullet.fraction))) if bullet.fraction else 0
            if filled:
                pyxel.rect(bar_x,row_y+2*scale,filled,4,10)
        if width>=timer_width+id_width+6:
            label(pyxel,x+width-timer_width,row_y,_seconds(bullet.remaining_seconds),0,scale=scale)
    footer=('No bullets in flight' if not status.bullets else
            f'{offset+1}-{offset+len(rows)} of {len(status.bullets)}'
            + (' / scroll for more' if len(status.bullets)>capacity else ''))
    text(footer,bottom-8*scale,5)
    return capacity
